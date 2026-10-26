import os
import threading

from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from backend.common.exception import errors
from backend.core.conf import settings
from backend.core.path_conf import STATIC_DIR
from backend.plugin.ai_buddy.enums import AIBuddyDocumentExtractBackend, AIBuddyOcrBackend
from backend.plugin.ai_buddy.utils.knowledge_extract import extract_with_backend
from backend.plugin.ai_buddy.utils.knowledge_parser import KnowledgeSegment, join_knowledge_text_segments


def resolve_ocr_backend(value: str | None = None) -> AIBuddyOcrBackend:
    """
    解析当前 OCR 后端

    :param value: 配置原文，空则读取当前配置
    :return:
    """
    text = (value if value is not None else settings.AI_BUDDY_OCR_BACKEND) or ''
    try:
        return AIBuddyOcrBackend(str(text).strip().lower())
    except ValueError as exc:
        raise errors.RequestError(msg='OCR 后端配置无效') from exc


_OCR_READY_NAME = '.ready'
_OCR_WEIGHT_FILES: tuple[str, ...] = (
    'PP-OCRv6_det_small.onnx',
    'PP-OCRv6_rec_small.onnx',
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx',
)


def ocr_models_dir() -> Path:
    """RapidOCR ONNX 模型固定目录"""
    path = STATIC_DIR / 'ai_buddy' / 'ocr_models'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_rapidocr_downloaded() -> bool:
    """判断固定目录中是否已有 RapidOCR ONNX 权重"""
    root = ocr_models_dir()
    if (root / _OCR_READY_NAME).is_file():
        return True
    return all((root / name).is_file() for name in _OCR_WEIGHT_FILES)


def _require_rapidocr_downloaded() -> None:
    """要求 RapidOCR 模型已下载到固定目录"""
    if not _is_rapidocr_downloaded():
        raise errors.RequestError(msg='RapidOCR 模型尚未下载')


def list_onnx_ocr_options() -> list[dict[str, object]]:
    """列出本地 ONNX OCR 选项，含体积和下载状态"""
    return [
        {
            'id': 'rapidocr',
            'name': 'RapidOCR',
            'size_gb': 0.02,
            'downloaded': _is_rapidocr_downloaded(),
        }
    ]


@dataclass
class OcrOnnxDownloadState:
    """RapidOCR 模型下载状态"""

    status: str = 'idle'
    progress: float = 0.0
    model_id: str = ''
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """导出下载进度、错误和本地缓存目录"""
        return {
            'status': self.status,
            'progress': self.progress,
            'model_id': self.model_id,
            'error': self.error,
            'cache_dir': str(ocr_models_dir()),
        }


_ocr_download_lock = threading.Lock()
_ocr_download_state = OcrOnnxDownloadState()


def get_ocr_onnx_download_status() -> dict[str, object]:
    """当前 RapidOCR 下载状态"""
    with _ocr_download_lock:
        return _ocr_download_state.to_dict()


def _set_ocr_download_state(**kwargs: object) -> None:
    with _ocr_download_lock:
        for key, value in kwargs.items():
            setattr(_ocr_download_state, key, value)


def _run_ocr_onnx_download() -> None:
    try:
        os.nice(10)
    except OSError:
        pass
    try:
        from rapidocr import download_models
    except ImportError:
        _set_ocr_download_state(status='failed', error='本地 ONNX OCR 需要安装 rapidocr 和 onnxruntime')
        return
    try:
        _set_ocr_download_state(status='downloading', progress=0.1, error=None)
        import rapidocr

        from omegaconf import OmegaConf

        destination = ocr_models_dir() / 'config.yaml'
        source = Path(rapidocr.__file__).resolve().parent / 'config.yaml'
        config = OmegaConf.load(source)
        config.Global.model_root_dir = str(ocr_models_dir())
        OmegaConf.save(config, destination)
        download_models(destination)
        if not _is_rapidocr_downloaded():
            raise RuntimeError('下载完成但未找到 ONNX 权重')
        (ocr_models_dir() / _OCR_READY_NAME).write_text('1', encoding='utf-8')
        _set_ocr_download_state(status='done', progress=1.0, error=None)
    except Exception as exc:
        _set_ocr_download_state(status='failed', progress=0.0, error=str(exc))


def start_ocr_onnx_download(model_id: str = 'rapidocr') -> dict[str, object]:
    """
    开始下载 RapidOCR 模型到固定目录

    :param model_id: OCR 模型 ID
    :return:
    """
    selected = (model_id or 'rapidocr').strip() or 'rapidocr'
    if selected != 'rapidocr':
        raise errors.RequestError(msg='ONNX OCR 模型不在目录中')
    with _ocr_download_lock:
        if _ocr_download_state.status == 'downloading':
            raise errors.RequestError(msg='已有 OCR 模型正在下载')
        downloaded = _is_rapidocr_downloaded()
        _ocr_download_state.status = 'done' if downloaded else 'downloading'
        _ocr_download_state.progress = 1.0 if downloaded else 0.0
        _ocr_download_state.model_id = selected
        _ocr_download_state.error = None
    if downloaded:
        return get_ocr_onnx_download_status()
    threading.Thread(target=_run_ocr_onnx_download, name='ai-buddy-ocr-onnx-download', daemon=True).start()
    return get_ocr_onnx_download_status()


def paddleocr_models_dir() -> Path:
    """本机 PaddleOCR 模型固定目录"""
    path = STATIC_DIR / 'ai_buddy' / 'paddleocr_models'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_paddleocr_downloaded() -> bool:
    """按初始化完成标记判断 PaddleOCR 模型是否就绪"""
    return (paddleocr_models_dir() / _OCR_READY_NAME).is_file()


def _require_paddleocr_downloaded() -> None:
    """要求 PaddleOCR 模型已下载到固定目录"""
    if not _is_paddleocr_downloaded():
        raise errors.RequestError(msg='PaddleOCR 模型尚未下载')


def list_paddleocr_options() -> list[dict[str, object]]:
    """列出本机 PaddleOCR 选项，含体积和下载状态"""
    return [
        {
            'id': 'paddleocr',
            'name': 'PaddleOCR 中文检测识别',
            'size_gb': 0.08,
            'downloaded': _is_paddleocr_downloaded(),
        }
    ]


@dataclass
class PaddleocrDownloadState:
    """PaddleOCR 模型下载状态"""

    status: str = 'idle'
    progress: float = 0.0
    model_id: str = ''
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """导出下载进度、错误和本地缓存目录"""
        return {
            'status': self.status,
            'progress': self.progress,
            'model_id': self.model_id,
            'error': self.error,
            'cache_dir': str(paddleocr_models_dir()),
        }


_paddleocr_download_lock = threading.Lock()
_paddleocr_download_state = PaddleocrDownloadState()
_paddleocr_engine = None
_rapidocr_engine: Any = None
_rapidocr_lock = threading.Lock()


def get_paddleocr_download_status() -> dict[str, object]:
    """当前 PaddleOCR 下载状态"""
    with _paddleocr_download_lock:
        return _paddleocr_download_state.to_dict()


def _set_paddleocr_download_state(**kwargs: object) -> None:
    with _paddleocr_download_lock:
        for key, value in kwargs.items():
            setattr(_paddleocr_download_state, key, value)


def _create_paddleocr_engine() -> object:
    from paddleocr import PaddleOCR

    root = paddleocr_models_dir()
    os.environ['PADDLEOCR_HOME'] = str(root)
    os.environ['PADDLE_PDX_CACHE_HOME'] = str(root)
    return PaddleOCR(lang='ch', use_doc_orientation_classify=False, use_doc_unwarping=False)


def _run_paddleocr_download() -> None:
    global _paddleocr_engine
    try:
        os.nice(10)
    except OSError:
        pass
    try:
        _set_paddleocr_download_state(status='downloading', progress=0.1, error=None)
        _paddleocr_engine = _create_paddleocr_engine()
        (paddleocr_models_dir() / _OCR_READY_NAME).write_text('1', encoding='utf-8')
        _set_paddleocr_download_state(status='done', progress=1.0, error=None)
    except ImportError:
        _set_paddleocr_download_state(status='failed', error='本机 PaddleOCR 需要安装 paddleocr')
    except Exception as exc:
        _set_paddleocr_download_state(status='failed', progress=0.0, error=str(exc))


def start_paddleocr_download(model_id: str = 'paddleocr') -> dict[str, object]:
    """
    开始下载 PaddleOCR 模型到固定目录

    :param model_id: OCR 模型 ID
    :return:
    """
    selected = (model_id or 'paddleocr').strip() or 'paddleocr'
    if selected != 'paddleocr':
        raise errors.RequestError(msg='PaddleOCR 模型不在目录中')
    with _paddleocr_download_lock:
        if _paddleocr_download_state.status == 'downloading':
            raise errors.RequestError(msg='已有 PaddleOCR 模型正在下载')
        downloaded = _is_paddleocr_downloaded()
        _paddleocr_download_state.status = 'done' if downloaded else 'downloading'
        _paddleocr_download_state.progress = 1.0 if downloaded else 0.0
        _paddleocr_download_state.model_id = selected
        _paddleocr_download_state.error = None
    if downloaded:
        return get_paddleocr_download_status()
    threading.Thread(target=_run_paddleocr_download, name='ai-buddy-paddleocr-download', daemon=True).start()
    return get_paddleocr_download_status()


def join_ocr_segments(segments: Sequence[KnowledgeSegment], texts: Sequence[str]) -> str:
    """
    用 OCR 结果替换图片片段并拼接正文

    :param segments: 解析片段
    :param texts: 与图片片段顺序对应的 OCR 文本
    :return:
    """
    resolved: list[KnowledgeSegment] = []
    cursor = 0
    for segment in segments:
        if segment.image is None:
            resolved.append(segment)
            continue
        text = texts[cursor].strip() if cursor < len(texts) else ''
        cursor += 1
        if text:
            resolved.append(KnowledgeSegment(text=text))
            continue
        if segment.placeholder:
            resolved.append(KnowledgeSegment(placeholder=segment.placeholder))
    content = join_knowledge_text_segments(resolved)
    if not content:
        raise errors.RequestError(msg='知识内容不能为空')
    return content


def ocr_images_with_system(images: Sequence[KnowledgeSegment]) -> list[str]:
    """
    使用本机 OCR：优先 Tesseract，其次 PaddleOCR

    :param images: 含图片字节的片段
    :return:
    """
    try:
        return _ocr_images_with_tesseract(images)
    except errors.RequestError:
        return ocr_images_with_paddleocr(images)


def _ocr_images_with_tesseract(images: Sequence[KnowledgeSegment]) -> list[str]:
    """
    使用 Tesseract 识别图片文字

    :param images: 含图片字节的片段
    :return:
    """
    texts: list[str] = []
    for segment in images:
        try:
            import pytesseract

            from PIL import Image
        except ImportError as exc:
            raise errors.RequestError(
                msg='Tesseract OCR 需要安装 pytesseract 和 pillow，并在主机安装 tesseract'
            ) from exc
        if not segment.image:
            texts.append('')
            continue
        try:
            texts.append(pytesseract.image_to_string(Image.open(BytesIO(segment.image))).strip())
        except Exception as exc:
            raise errors.RequestError(msg='Tesseract OCR 失败，请确认已安装 tesseract') from exc
    return texts


def ocr_images_with_onnx(images: Sequence[KnowledgeSegment]) -> list[str]:
    """
    使用 RapidOCR（本地 ONNX）识别图片文字

    :param images: 含图片字节的片段
    :return:
    """
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise errors.RequestError(msg='本地 ONNX OCR 需要安装 rapidocr 和 onnxruntime') from exc
    _require_rapidocr_downloaded()
    if not images:
        return []
    global _rapidocr_engine
    try:
        with _rapidocr_lock:
            if _rapidocr_engine is None:
                _rapidocr_engine = RapidOCR(params={'Global.model_root_dir': str(ocr_models_dir())})
            engine = _rapidocr_engine
    except Exception as exc:
        raise errors.RequestError(msg='RapidOCR 初始化失败') from exc
    texts: list[str] = []
    for segment in images:
        if not segment.image:
            texts.append('')
            continue
        try:
            result = engine(segment.image)
        except Exception as exc:
            raise errors.RequestError(msg='RapidOCR 识别失败') from exc
        lines = getattr(result, 'txts', None)
        if isinstance(lines, (list, tuple)):
            texts.append('\n'.join(str(line).strip() for line in lines if str(line).strip()))
            continue
        texts.append(str(lines or '').strip())
    return texts


def ocr_images_with_paddleocr(images: Sequence[KnowledgeSegment]) -> list[str]:
    """
    使用 PaddleOCR 识别图片文字

    :param images: 含图片字节的片段
    :return:
    """
    global _paddleocr_engine
    api_url = settings.AI_BUDDY_PADDLEOCR_API_URL.strip()
    texts: list[str] = []
    for segment in images:
        if api_url:
            import httpx

            if not segment.image:
                texts.append('')
                continue
            try:
                with httpx.Client(timeout=60) as client:
                    response = client.post(
                        api_url.rstrip('/'),
                        files={'file': ('image.png', segment.image, segment.media_type or 'image/png')},
                    )
                    response.raise_for_status()
                    payload = response.json()
            except Exception as exc:
                raise errors.RequestError(msg='PaddleOCR 服务解析失败，请检查地址') from exc
            texts.append(
                str(payload.get('text') or payload.get('md_content') or '').strip() if isinstance(payload, dict) else ''
            )
            continue
        _require_paddleocr_downloaded()
        if not segment.image:
            texts.append('')
            continue
        try:
            import numpy as np

            from PIL import Image

            if _paddleocr_engine is None:
                _paddleocr_engine = _create_paddleocr_engine()
            with Image.open(BytesIO(segment.image)) as image:
                pixels = np.asarray(image.convert('RGB'))[:, :, ::-1].copy()
            result = _paddleocr_engine.predict(pixels)
        except ImportError as exc:
            raise errors.RequestError(msg='PaddleOCR 需要安装 paddleocr，或配置自建服务地址') from exc
        except Exception as exc:
            raise errors.RequestError(msg='PaddleOCR 识别失败') from exc
        lines: list[str] = []
        for page in result:
            lines.extend(str(text).strip() for text in page['rec_texts'])
        texts.append('\n'.join(item for item in lines if item).strip())
    return texts


def ocr_images_with_mistral(images: Sequence[KnowledgeSegment]) -> list[str]:
    """
    使用 Mistral OCR 识别图片文字

    :param images: 含图片字节的片段
    :return:
    """
    texts: list[str] = []
    for item in images:
        if not item.image:
            texts.append('')
            continue
        ext = 'png'
        if item.media_type == 'image/jpeg':
            ext = 'jpg'
        texts.append(
            extract_with_backend(
                backend=AIBuddyDocumentExtractBackend.mistral,
                filename=f'page.{ext}',
                data=item.image,
                ext=ext,
            )
        )
    return texts
