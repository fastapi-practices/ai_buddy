import base64
import time

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.enums import AIBuddyDocumentExtractBackend

_UNSTRUCTURED_DEFAULT_API_URL = 'https://api.unstructuredapp.io/general/v0/general'
_MINERU_API_BASE = 'https://mineru.net/api/v4'
_DOC2X_DEFAULT_API_URL = 'https://v2.doc2x.noedgeai.com'
_MISTRAL_DEFAULT_API_URL = 'https://api.mistral.ai'
_POLL_SECONDS = 2
_POLL_ATTEMPTS = 90


# 各后端协议按分支直接处理，避免一次调用的转发层
def extract_with_backend(  # ruff: ignore[complex-structure]
    *, backend: AIBuddyDocumentExtractBackend, filename: str, data: bytes, ext: str
) -> str:
    """
    用指定后端抽取文档正文，失败返回空字符串供 OCR 回退

    :param backend: 抽取后端
    :param filename: 文件名
    :param data: 文件内容
    :param ext: 扩展名
    :return:
    """
    if backend == AIBuddyDocumentExtractBackend.markitdown:
        try:
            from markitdown import MarkItDown
        except ImportError as exc:
            raise errors.RequestError(msg='MarkItDown 解析需要安装 markitdown') from exc
        endpoint = settings.AI_BUDDY_MARKITDOWN_DOCINTEL_ENDPOINT.strip()
        api_key = settings.AI_BUDDY_MARKITDOWN_DOCINTEL_API_KEY.strip()
        kwargs: dict[str, object] = {}
        if endpoint:
            if not api_key:
                raise errors.RequestError(msg='MarkItDown Azure 文档智能需要配置 API Key')
            try:
                from azure.core.credentials import AzureKeyCredential
            except ImportError:
                raise errors.RequestError(msg='Azure 文档智能需要安装 azure-core')
            kwargs = {'docintel_endpoint': endpoint, 'docintel_credential': AzureKeyCredential(api_key)}
        converter = MarkItDown(**kwargs)
        try:
            if endpoint:
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=True) as tmp:
                    tmp.write(data)
                    tmp.flush()
                    result = converter.convert(tmp.name)
            else:
                try:
                    result = converter.convert_stream(BytesIO(data), file_extension=f'.{ext}', file_name=filename)
                except (TypeError, AttributeError):
                    result = converter.convert(BytesIO(data), file_extension=f'.{ext}')
        except errors.RequestError:
            raise
        except Exception as exc:
            raise errors.RequestError(msg='MarkItDown 解析失败') from exc
        return str(getattr(result, 'text_content', '') or '').strip()
    if backend == AIBuddyDocumentExtractBackend.unstructured:
        api_key = settings.AI_BUDDY_UNSTRUCTURED_API_KEY.strip()
        if api_key:
            url = settings.AI_BUDDY_UNSTRUCTURED_API_URL.strip() or _UNSTRUCTURED_DEFAULT_API_URL
            try:
                with httpx.Client(timeout=120) as client:
                    response = client.post(
                        url,
                        headers={'accept': 'application/json', 'unstructured-api-key': api_key},
                        files={'files': (Path(filename).name or 'document', data)},
                        data={'strategy': 'auto'},
                    )
                    response.raise_for_status()
                    payload = response.json()
            except Exception as exc:
                raise errors.RequestError(msg='Unstructured API 解析失败，请检查地址和密钥') from exc
            if not isinstance(payload, list):
                raise errors.RequestError(msg='Unstructured API 返回无效')
            texts = [str(item.get('text') or '').strip() for item in payload if isinstance(item, dict)]
            return '\n\n'.join(item for item in texts if item).strip()
        try:
            from unstructured.partition.auto import partition
        except ImportError as exc:
            raise errors.RequestError(msg='Unstructured 解析需要配置 API Key，或安装 unstructured 本地解析') from exc
        try:
            elements = partition(file=BytesIO(data), metadata_filename=filename)
        except Exception as exc:
            raise errors.RequestError(msg='Unstructured 解析失败') from exc
        texts = [str(getattr(item, 'text', '') or '').strip() for item in elements]
        return '\n\n'.join(item for item in texts if item).strip()
    if backend == AIBuddyDocumentExtractBackend.mineru:
        api_key = settings.AI_BUDDY_MINERU_API_KEY.strip()
        if not api_key:
            raise errors.RequestError(msg='MinerU 云解析需要配置 API Key')
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        name = Path(filename).name or 'document.pdf'
        with httpx.Client(timeout=60) as client:
            upload = client.post(
                f'{_MINERU_API_BASE}/file-urls/batch',
                headers=headers,
                json={'files': [{'name': name}]},
            )
            try:
                upload.raise_for_status()
                upload_payload = upload.json()
            except Exception as exc:
                raise errors.RequestError(msg='MinerU 申请上传地址失败，请检查密钥') from exc
            file_urls = (upload_payload.get('data') or {}).get('file_urls') or []
            if not file_urls:
                raise errors.RequestError(msg='MinerU 未返回上传地址')
            put_url = file_urls[0] if isinstance(file_urls[0], str) else str(file_urls[0].get('url') or '')
            put = client.put(put_url, content=data)
            try:
                put.raise_for_status()
            except Exception as exc:
                raise errors.RequestError(msg='MinerU 上传文件失败') from exc
            task = client.post(
                f'{_MINERU_API_BASE}/extract/task',
                headers=headers,
                json={'url': put_url, 'model_version': 'vlm', 'is_ocr': True, 'enable_table': True},
            )
            try:
                task.raise_for_status()
                task_id = str((task.json().get('data') or {}).get('task_id') or '')
            except Exception as exc:
                raise errors.RequestError(msg='MinerU 创建解析任务失败') from exc
            if not task_id:
                raise errors.RequestError(msg='MinerU 未返回任务 ID')
            for _ in range(_POLL_ATTEMPTS):
                response = client.get(f'{_MINERU_API_BASE}/extract/task/{task_id}', headers=headers)
                response.raise_for_status()
                result_data = response.json().get('data') or {}
                state = str(result_data.get('state') or result_data.get('status') or '')
                if state in {'done', 'success', 'completed'}:
                    zip_url = str(result_data.get('full_zip_url') or result_data.get('zip_url') or '')
                    if not zip_url:
                        raise errors.RequestError(msg='MinerU 解析完成但未返回结果')
                    break
                if state in {'failed', 'error'}:
                    raise errors.RequestError(msg='MinerU 解析失败')
                time.sleep(_POLL_SECONDS)
            else:
                raise errors.RequestError(msg='MinerU 解析超时')

        with httpx.Client(timeout=120) as client:
            response = client.get(zip_url)
            response.raise_for_status()
            raw = response.content
        markdowns: list[str] = []
        with ZipFile(BytesIO(raw)) as archive:
            for info in archive.infolist():
                if info.is_dir() or not info.filename.lower().endswith('.md'):
                    continue
                markdowns.append(archive.read(info.filename).decode('utf-8', errors='ignore').strip())
        return '\n\n'.join(item for item in markdowns if item).strip()
    if backend == AIBuddyDocumentExtractBackend.open_mineru:
        base = settings.AI_BUDDY_OPEN_MINERU_API_URL.strip().rstrip('/')
        if not base:
            raise errors.RequestError(msg='Open MinerU 需要配置自建服务地址')
        headers: dict[str, str] = {}
        api_key = settings.AI_BUDDY_OPEN_MINERU_API_KEY.strip()
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        try:
            with httpx.Client(timeout=180) as client:
                response = client.post(
                    f'{base}/file_parse',
                    headers=headers,
                    files={'files': (Path(filename).name or 'document.pdf', data)},
                    data={'backend': 'pipeline', 'return_md': 'true'},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise errors.RequestError(msg='Open MinerU 解析失败，请检查自建服务地址') from exc
        results = payload.get('results') if isinstance(payload, dict) else None
        if isinstance(results, dict):
            for item in results.values():
                if isinstance(item, dict) and item.get('md_content'):
                    return str(item['md_content']).strip()
        if isinstance(payload, dict) and payload.get('md_content'):
            return str(payload['md_content']).strip()
        return str(payload.get('content') or '').strip() if isinstance(payload, dict) else ''
    if backend == AIBuddyDocumentExtractBackend.doc2x:
        api_key = settings.AI_BUDDY_DOC2X_API_KEY.strip()
        if not api_key:
            raise errors.RequestError(msg='Doc2X 解析需要配置 API Key')
        base = settings.AI_BUDDY_DOC2X_API_URL.strip().rstrip('/') or _DOC2X_DEFAULT_API_URL
        headers = {'Authorization': f'Bearer {api_key}'}
        with httpx.Client(timeout=60) as client:
            pre = client.post(f'{base}/api/v2/parse/preupload', headers=headers)
            try:
                pre.raise_for_status()
                pre_payload = pre.json()
                pre_data = (pre_payload.get('data') or {}) if isinstance(pre_payload, dict) else {}
            except Exception as exc:
                raise errors.RequestError(msg='Doc2X 申请上传失败，请检查密钥') from exc
            upload_url = str(pre_data.get('url') or '')
            uid = str(pre_data.get('uid') or '')
            if not upload_url or not uid:
                raise errors.RequestError(msg='Doc2X 未返回上传地址')
            put = client.put(upload_url, content=data)
            try:
                put.raise_for_status()
            except Exception as exc:
                raise errors.RequestError(msg='Doc2X 上传文件失败') from exc
            for _ in range(_POLL_ATTEMPTS):
                response = client.get(f'{base}/api/v2/parse/status', headers=headers, params={'uid': uid})
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise errors.RequestError(msg='Doc2X 返回格式无效')
                result_data = payload.get('data')
                status = str((result_data or {}).get('status') or payload.get('code') or '')
                if status in {'success', 'ok'}:
                    result_data = result_data or payload
                    break
                if status in {'failed', 'error', 'parse_error'}:
                    raise errors.RequestError(msg='Doc2X 解析失败')
                time.sleep(_POLL_SECONDS)
            else:
                raise errors.RequestError(msg='Doc2X 解析超时')

        if result_data.get('md'):
            return str(result_data['md']).strip()
        result = result_data.get('result')
        if isinstance(result, dict) and result.get('markdown'):
            return str(result['markdown']).strip()
        pages = []
        if isinstance(result, dict):
            pages = result.get('pages') or []
        elif isinstance(result_data.get('pages'), list):
            pages = result_data['pages']
        if isinstance(pages, list):
            texts = [
                str(item.get('md') or item.get('markdown') or '').strip() for item in pages if isinstance(item, dict)
            ]
            return '\n\n'.join(item for item in texts if item).strip()
        return ''
    if backend == AIBuddyDocumentExtractBackend.mistral:
        api_key = settings.AI_BUDDY_MISTRAL_API_KEY.strip()
        if not api_key:
            raise errors.RequestError(msg='Mistral OCR 需要配置 API Key')
        base = settings.AI_BUDDY_MISTRAL_API_URL.strip().rstrip('/') or _MISTRAL_DEFAULT_API_URL
        media_type = (
            'application/pdf'
            if ext == 'pdf'
            else f'image/{ext}'
            if ext in {'png', 'jpg', 'jpeg', 'webp', 'gif'}
            else (
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                if ext == 'docx'
                else 'application/octet-stream'
            )
        )
        encoded = base64.b64encode(data).decode()
        document_type = 'image_url' if ext in {'png', 'jpg', 'jpeg', 'webp', 'gif'} else 'document_url'
        body = {
            'model': 'mistral-ocr-latest',
            'document': {'type': document_type, document_type: f'data:{media_type};base64,{encoded}'},
            'include_image_base64': False,
        }
        try:
            with httpx.Client(timeout=180) as client:
                response = client.post(
                    f'{base}/v1/ocr',
                    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise errors.RequestError(msg='Mistral OCR 解析失败，请检查密钥') from exc
        pages = payload.get('pages') if isinstance(payload, dict) else None
        if isinstance(pages, list):
            texts = [
                str(item.get('markdown') or item.get('text') or '').strip() for item in pages if isinstance(item, dict)
            ]
            return '\n\n'.join(item for item in texts if item).strip()
        return str(payload.get('text') or payload.get('markdown') or '').strip() if isinstance(payload, dict) else ''
    return ''
