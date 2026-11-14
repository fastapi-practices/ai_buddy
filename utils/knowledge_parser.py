import contextlib
import json

from collections.abc import Mapping, Sequence
from io import BytesIO
from math import ceil
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.dataclasses import KnowledgeSegment, KnowledgeUpload
from backend.plugin.ai_buddy.enums import AIBuddyDocumentExtractBackend, AIBuddyKnowledgeFileType
from backend.plugin.ai_buddy.utils.archive import validate_archive_size
from backend.plugin.ai_buddy.utils.knowledge_extract import extract_with_backend
from backend.plugin.ai_buddy.utils.workspace import safe_relative_parts

_TEXT_EXTS = frozenset({'md', 'markdown', 'txt', 'text'})
_OFFICE_EXTS = frozenset({'pdf', 'docx', 'pptx', 'xlsx'})
_IMAGE_EXTS = frozenset({'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tif', 'tiff'})
_KNOWLEDGE_EXTS = _TEXT_EXTS | _OFFICE_EXTS | _IMAGE_EXTS
_PDF_RENDER_SCALE = 2
_IMAGE_MEDIA_TYPES = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'webp': 'image/webp',
    'gif': 'image/gif',
    'bmp': 'image/bmp',
    'tif': 'image/tiff',
    'tiff': 'image/tiff',
}


def _resolve_document_extract_backend(value: str | None = None) -> AIBuddyDocumentExtractBackend:
    """
    解析文档抽取后端，非法值回退内置解析

    :param value: 配置原文，空则读取当前配置
    :return:
    """
    text = (value if value is not None else settings.AI_BUDDY_DOCUMENT_EXTRACT_BACKEND) or ''
    try:
        return AIBuddyDocumentExtractBackend(str(text).strip().lower())
    except ValueError:
        return AIBuddyDocumentExtractBackend.native


def parse_knowledge_texts(value: str | None) -> dict[str, str]:
    """
    解析客户端提交的 OCR 文本

    :param value: JSON 对象原文，键为文件名或 zip 内路径
    :return:
    """
    text = (value or '').strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise errors.RequestError(msg='texts 需要是文件名到文本的 JSON 对象') from exc
    if not isinstance(payload, dict):
        raise errors.RequestError(msg='texts 需要是文件名到文本的 JSON 对象')
    texts: dict[str, str] = {}
    for key, item in payload.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise errors.RequestError(msg='texts 的键和值都需要是文本')
        if key.strip() and item.strip():
            texts[key.strip()] = item.strip()
    return texts


# 目录、压缩包与文件格式校验共同决定本次上传结果
def parse_knowledge_uploads(  # ruff: ignore[complex-structure]
    *,
    files: Sequence[tuple[str | None, bytes]],
    title: str | None = None,
    texts: Mapping[str, str] | None = None,
) -> list[KnowledgeUpload]:
    """
    解析上传的知识文件、目录或 zip

    :param files: 知识文件、目录或包含 md、txt 的 zip
    :param title: 可选标题，仅单个文件时生效，空值使用文件名
    :param texts: 客户端已完成的 OCR 文本，键为文件名或 zip 内路径
    :return:
    """
    if not files:
        raise errors.RequestError(msg='请上传知识文件、目录或 zip')
    if len(files) > settings.AI_BUDDY_KNOWLEDGE_MAX_FILES:
        raise errors.RequestError(msg='知识文件数量超出限制')
    if sum(len(data) for _, data in files) > settings.AI_BUDDY_KNOWLEDGE_MAX_TOTAL_BYTES:
        raise errors.RequestError(msg='知识文件总大小超出限制')
    payloads: list[tuple[str, bytes]] = []
    for filename, data in files:
        source = (filename or '').replace('\\', '/').strip()
        if not source:
            raise errors.RequestError(msg='文件名不能为空')
        if not data:
            raise errors.RequestError(msg='文件内容不能为空')
        if len(data) > settings.S3_UPLOAD_SIZE_MAX:
            raise errors.RequestError(msg='文件超出最大限制')
        name = Path(source).name
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        if ext != 'zip' and ext not in _KNOWLEDGE_EXTS:
            raise errors.RequestError(msg='知识仅支持 md、txt、pdf、docx、pptx、xlsx、图片或包含这些文件的 zip')
        payloads.append((source, data))
    documents: list[tuple[str, bytes]] = []
    for filename, data in payloads:
        if Path(filename).name.lower().endswith('.zip'):
            try:
                archive = ZipFile(BytesIO(data))
            except BadZipFile as exc:
                raise errors.RequestError(msg='知识 zip 文件无效') from exc
            with archive:
                validate_archive_size(archive, msg='知识 zip 解压后超出最大限制')
                entries: list[tuple[str, bytes]] = []
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    parts = safe_relative_parts(info.filename, msg='知识路径包含非法路径')
                    if not parts or any(part == '__MACOSX' or part.startswith('.') for part in parts):
                        continue
                    ext = parts[-1].rsplit('.', 1)[-1].lower() if '.' in parts[-1] else ''
                    if ext not in _KNOWLEDGE_EXTS:
                        continue
                    with archive.open(info) as file:
                        content = file.read(settings.S3_UPLOAD_SIZE_MAX + 1)
                    if len(content) > settings.S3_UPLOAD_SIZE_MAX:
                        raise errors.RequestError(msg='文件超出最大限制')
                    entries.append(('/'.join(parts), content))
                if not entries:
                    raise errors.RequestError(msg='zip 中未找到可解析的知识文件')
                documents.extend(entries)
            continue
        documents.append((filename, data))
    if not documents:
        raise errors.RequestError(msg='未找到可解析的知识文件')
    if len(documents) > settings.AI_BUDDY_KNOWLEDGE_MAX_FILES:
        raise errors.RequestError(msg='知识文件数量超出限制')
    resolved_title = (title or '').strip() or None
    if resolved_title and len(documents) > 1:
        raise errors.RequestError(msg='批量上传不能指定标题')
    client_texts = {key.strip(): value.strip() for key, value in (texts or {}).items() if key.strip() and value.strip()}
    uploads: list[KnowledgeUpload] = []
    image_count = image_pixels = 0
    for filename, data in documents:
        source = '/'.join(safe_relative_parts(filename, msg='知识路径包含非法路径'))
        if not source:
            raise errors.RequestError(msg='文件名不能为空')
        ext = Path(source).suffix.lower().lstrip('.')
        file_type = (
            AIBuddyKnowledgeFileType.image
            if ext in _IMAGE_EXTS
            else AIBuddyKnowledgeFileType({'markdown': 'md', 'text': 'txt'}.get(ext, ext))
        )
        segments: list[KnowledgeSegment] = []
        client_text = client_texts.get(source) or client_texts.get(Path(source).name) or ''
        if client_text:
            segments.append(KnowledgeSegment(text=client_text))
        elif ext in _TEXT_EXTS:
            try:
                text = data.decode('utf-8-sig').strip()
            except UnicodeDecodeError as exc:
                raise errors.RequestError(msg='文本知识文件必须使用 UTF-8 编码') from exc
            if text:
                segments.append(KnowledgeSegment(text=text))
        elif ext in _IMAGE_EXTS:
            segments.append(
                KnowledgeSegment(
                    image=data,
                    media_type=_IMAGE_MEDIA_TYPES.get(ext, 'application/octet-stream'),
                    placeholder=f'[image] {Path(source).name}',
                )
            )
        else:
            backend = _resolve_document_extract_backend()
            if backend != AIBuddyDocumentExtractBackend.native and ext in _OFFICE_EXTS:
                if ext == 'pdf':
                    _validate_pdf_page_count(data)
                text = extract_with_backend(backend=backend, filename=source, data=data, ext=ext)
                if text:
                    segments.append(KnowledgeSegment(text=text))
                elif ext == 'pdf':
                    segments = _extract_pdf_segments(data)
            elif ext == 'pdf':
                segments = _extract_pdf_segments(data)
            else:
                if ext == 'docx':
                    try:
                        from docx import Document
                    except ImportError as exc:
                        raise errors.RequestError(msg='解析 docx 需要安装 python-docx') from exc
                    document = Document(BytesIO(data))
                    text = '\n'.join(item.text.strip() for item in document.paragraphs if item.text.strip()).strip()
                elif ext == 'pptx':
                    try:
                        from pptx import Presentation
                    except ImportError as exc:
                        raise errors.RequestError(msg='解析 pptx 需要安装 python-pptx') from exc
                    presentation = Presentation(BytesIO(data))
                    slide_texts: list[str] = []
                    for slide in presentation.slides:
                        for shape in slide.shapes:
                            value = getattr(shape, 'text', None)
                            if isinstance(value, str) and value.strip():
                                slide_texts.append(value.strip())
                    text = '\n'.join(slide_texts).strip()
                elif ext == 'xlsx':
                    try:
                        from openpyxl import load_workbook
                    except ImportError as exc:
                        raise errors.RequestError(msg='解析 xlsx 需要安装 openpyxl') from exc
                    workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
                    rows: list[str] = []
                    try:
                        for sheet in workbook.worksheets:
                            for row in sheet.iter_rows(values_only=True):
                                values = [str(item).strip() for item in row if item is not None and str(item).strip()]
                                if values:
                                    rows.append('\t'.join(values))
                    finally:
                        workbook.close()
                    text = '\n'.join(rows).strip()
                else:
                    raise errors.RequestError(msg='不支持的知识文件类型')
                if text:
                    segments.append(KnowledgeSegment(text=text))
        image_count, image_pixels = _accumulate_image_limits(
            segments,
            image_count=image_count,
            image_pixels=image_pixels,
        )
        content = join_knowledge_text_segments(segments)
        if not content and not any(item.image for item in segments):
            raise errors.RequestError(msg='知识内容不能为空')
        document_title = resolved_title or Path(source).stem.strip()
        if not document_title:
            raise errors.RequestError(msg='知识标题不能为空')
        uploads.append(
            KnowledgeUpload(
                title=document_title,
                content=content,
                source=source,
                file_type=file_type,
                segments=tuple(segments),
            )
        )
    return uploads


def join_knowledge_text_segments(segments: Sequence[KnowledgeSegment]) -> str:
    """
    拼接无需 OCR 的文本片段和占位符

    :param segments: 解析片段
    :return:
    """
    parts: list[str] = []
    for segment in segments:
        if segment.text:
            parts.append(segment.text)
        elif segment.placeholder:
            parts.append(segment.placeholder)
    return '\n\n'.join(parts).strip()


def _validate_pdf_page_count(data: bytes) -> None:
    """
    在解析或调用外部抽取服务前限制 PDF 页数

    :param data: PDF 文件字节
    :return:
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise errors.RequestError(msg='解析 PDF 需要安装 pypdf') from exc
    try:
        page_count = len(PdfReader(BytesIO(data)).pages)
    except Exception as exc:
        raise errors.RequestError(msg='PDF 文件无效') from exc
    if page_count > settings.AI_BUDDY_KNOWLEDGE_MAX_PDF_PAGES:
        raise errors.RequestError(msg='PDF 页数超出限制')


def _accumulate_image_limits(
    segments: Sequence[KnowledgeSegment],
    *,
    image_count: int,
    image_pixels: int,
) -> tuple[int, int]:
    """
    累计校验本次上传的图片数量与像素预算，字节上限按单张图片校验

    :param segments: 当前文件的解析片段
    :param image_count: 已累计图片数量
    :param image_pixels: 已累计图片像素数
    :return:
    """
    images = [segment.image for segment in segments if segment.image]
    if not images:
        return image_count, image_pixels
    try:
        from PIL import Image
    except ImportError as exc:
        raise errors.RequestError(msg='解析知识图片需要安装 pillow') from exc
    for data in images:
        if len(data) > settings.AI_BUDDY_KNOWLEDGE_MAX_IMAGE_BYTES:
            raise errors.RequestError(msg='单张知识图片超出字节上限')
        image_count += 1
        if image_count > settings.AI_BUDDY_KNOWLEDGE_MAX_IMAGES:
            raise errors.RequestError(msg='知识图片数量超出限制')
        try:
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
        except Exception as exc:
            raise errors.RequestError(msg='知识图片格式无效') from exc
        image_pixels += width * height
        if image_pixels > settings.AI_BUDDY_KNOWLEDGE_MAX_IMAGE_PIXELS:
            raise errors.RequestError(msg='知识图片像素总数超出限制')
    return image_count, image_pixels


def _extract_pdf_segments(data: bytes) -> list[KnowledgeSegment]:  # ruff: ignore[complex-structure]
    """
    从 PDF 页面提取文档知识片段

    :param data: PDF 文件字节
    :return:
    """
    _validate_pdf_page_count(data)
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise errors.RequestError(msg='解析 PDF 需要安装 pypdf') from exc
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pdfium = None
    stream = BytesIO(data)
    reader = None
    document = None
    segments: list[KnowledgeSegment] = []
    rendered_pixels = 0
    try:
        try:
            reader = PdfReader(stream)
            pages = reader.pages
        except Exception as exc:
            raise errors.RequestError(msg='PDF 文件无效') from exc
        for index, page in enumerate(pages):
            try:
                text = (page.extract_text() or '').strip()
            except Exception as exc:
                raise errors.RequestError(msg='PDF 页面解析失败') from exc
            if text:
                segments.append(KnowledgeSegment(text=text))
                continue
            image: bytes | None = None
            if pdfium is not None:
                try:
                    if document is None:
                        document = pdfium.PdfDocument(data)
                    if 0 <= index < len(document):
                        media_box = page.mediabox
                        width = ceil(float(media_box.width) * _PDF_RENDER_SCALE)
                        height = ceil(float(media_box.height) * _PDF_RENDER_SCALE)
                        if rendered_pixels + width * height > settings.AI_BUDDY_KNOWLEDGE_MAX_IMAGE_PIXELS:
                            raise errors.RequestError(msg='PDF 渲染像素超出限制')
                        bitmap = document[index].render(scale=_PDF_RENDER_SCALE)
                        rendered = None
                        try:
                            rendered = bitmap.to_pil()
                            width, height = rendered.size
                            rendered_pixels += width * height
                            if rendered_pixels > settings.AI_BUDDY_KNOWLEDGE_MAX_IMAGE_PIXELS:
                                raise errors.RequestError(msg='PDF 渲染像素超出限制')
                            buffer = BytesIO()
                            rendered.save(buffer, format='PNG')
                            image = buffer.getvalue()
                        finally:
                            if rendered is not None:
                                rendered.close()
                            bitmap.close()
                except errors.RequestError:
                    raise
                except Exception:
                    pass
            if not image:
                image = next(
                    (
                        payload
                        for item in getattr(page, 'images', None) or []
                        if isinstance(payload := getattr(item, 'data', None), bytes) and payload
                    ),
                    None,
                )
            if image is not None:
                segments.append(KnowledgeSegment(image=image, media_type='image/png'))
    except errors.RequestError:
        raise
    except Exception as exc:
        raise errors.RequestError(msg='PDF 文件无效') from exc
    finally:
        if document is not None:
            with contextlib.suppress(Exception):
                document.close()
        if reader is not None:
            with contextlib.suppress(Exception):
                reader.close()
        with contextlib.suppress(Exception):
            stream.close()
    return segments
