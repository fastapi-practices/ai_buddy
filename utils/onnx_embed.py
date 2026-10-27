import os
import threading

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.common.exception import errors
from backend.core.path_conf import STATIC_DIR

ONNX_EMBEDDING_MODELS: tuple[str, ...] = (
    'BAAI/bge-small-zh-v1.5',
    'jinaai/jina-embeddings-v2-base-zh',
    'intfloat/multilingual-e5-large',
    'BAAI/bge-small-en-v1.5',
    'sentence-transformers/all-MiniLM-L6-v2',
)

_ONNX_SIZE_GB: dict[str, float] = {
    'BAAI/bge-small-zh-v1.5': 0.09,
    'jinaai/jina-embeddings-v2-base-zh': 0.32,
    'intfloat/multilingual-e5-large': 1.2,
    'BAAI/bge-small-en-v1.5': 0.13,
    'sentence-transformers/all-MiniLM-L6-v2': 0.09,
}

_ONNX_HF_SOURCE: dict[str, str] = {
    'BAAI/bge-small-zh-v1.5': 'Qdrant/bge-small-zh-v1.5',
    'jinaai/jina-embeddings-v2-base-zh': 'jinaai/jina-embeddings-v2-base-zh',
    'BAAI/bge-small-en-v1.5': 'qdrant/bge-small-en-v1.5-onnx-q',
    'sentence-transformers/all-MiniLM-L6-v2': 'qdrant/all-MiniLM-L6-v2-onnx',
    'intfloat/multilingual-e5-large': 'qdrant/multilingual-e5-large-onnx',
}

_ONNX_WEIGHT_FILE: dict[str, str] = {
    'BAAI/bge-small-zh-v1.5': 'model_optimized.onnx',
    'jinaai/jina-embeddings-v2-base-zh': 'onnx/model.onnx',
    'intfloat/multilingual-e5-large': 'model.onnx',
    'BAAI/bge-small-en-v1.5': 'model_optimized.onnx',
    'sentence-transformers/all-MiniLM-L6-v2': 'model.onnx',
}

_READY_NAME = '.ready'

_engine: Any = None
_engine_lock = threading.Lock()
_engine_model: str | None = None


def embedding_models_dir() -> Path:
    """ONNX 向量模型固定目录"""
    path = STATIC_DIR / 'ai_buddy' / 'embedding_models'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _model_cache_dir(model_id: str) -> Path:
    """
    单个模型的缓存目录

    :param model_id: 模型 ID
    :return:
    """
    return embedding_models_dir() / ('models--' + model_id.replace('/', '--'))


def _cache_names(model_id: str) -> list[str]:
    """
    汇总 ONNX 模型缓存名称

    :param model_id: 模型 ID
    :return:
    """
    names = [model_id]
    alias = _ONNX_HF_SOURCE.get(model_id)
    if alias and alias not in names:
        names.append(alias)
    return names


def _is_onnx_model_downloaded(model_id: str) -> bool:
    """
    判断固定目录中是否已有该 ONNX 向量模型权重

    :param model_id: 模型 ID
    :return:
    """
    weight = _ONNX_WEIGHT_FILE.get(model_id, 'model.onnx')
    for name in _cache_names(model_id):
        root = _model_cache_dir(name)
        if (root / _READY_NAME).is_file():
            return True
        refs = root / 'refs' / 'main'
        try:
            if not refs.is_file():
                continue
            revision = refs.read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if revision and (root / 'snapshots' / revision / weight).exists():
            return True
    return False


def require_onnx_model_downloaded(model_id: str) -> str:
    """
    要求模型已下载到固定目录

    :param model_id: 模型 ID
    :return:
    """
    selected = (model_id or '').strip()
    if selected not in ONNX_EMBEDDING_MODELS:
        raise errors.RequestError(msg='ONNX 向量模型不在目录中')
    if not _is_onnx_model_downloaded(selected):
        raise errors.RequestError(msg='所选 ONNX 向量模型尚未下载')
    return selected


def list_onnx_embedding_options() -> list[dict[str, object]]:
    """列出本地 ONNX 向量模型选项，含体积和下载状态"""
    return [
        {
            'id': model_id,
            'name': model_id,
            'size_gb': _ONNX_SIZE_GB.get(model_id),
            'downloaded': _is_onnx_model_downloaded(model_id),
        }
        for model_id in ONNX_EMBEDDING_MODELS
    ]


@dataclass
class OnnxDownloadState:
    """ONNX 向量模型下载状态"""

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
            'cache_dir': str(embedding_models_dir()),
        }


_download_lock = threading.Lock()
_download_state = OnnxDownloadState()


def get_onnx_download_status() -> dict[str, object]:
    """当前 ONNX 下载状态"""
    with _download_lock:
        return _download_state.to_dict()


def _set_download_state(**kwargs: object) -> None:
    """
    在锁保护下更新 ONNX 模型下载状态

    :param kwargs: 额外关键字参数
    :return:
    """
    with _download_lock:
        for key, value in kwargs.items():
            setattr(_download_state, key, value)


def _run_onnx_download(model_id: str) -> None:
    """
    在后台线程下载 ONNX 向量模型

    :param model_id: 模型 ID
    :return:
    """
    try:
        os.nice(10)
    except OSError:
        pass
    try:
        from fastembed import TextEmbedding
    except ImportError:
        _set_download_state(status='failed', error='下载 ONNX 模型需要安装 fastembed 和 huggingface_hub')
        return
    try:
        _set_download_state(status='downloading', progress=0.1, model_id=model_id, error=None)
        description = TextEmbedding._get_model_description(model_id)
        TextEmbedding.download_model(
            description,
            cache_dir=str(embedding_models_dir()),
            max_workers=1,
        )
        if not _is_onnx_model_downloaded(model_id):
            raise RuntimeError('下载完成但未找到 ONNX 权重')
        for name in _cache_names(model_id):
            root = _model_cache_dir(name)
            root.mkdir(parents=True, exist_ok=True)
            (root / _READY_NAME).write_text('1', encoding='utf-8')
        _set_download_state(status='done', progress=1.0, model_id=model_id, error=None)
    except Exception as exc:
        _set_download_state(status='failed', progress=0.0, model_id=model_id, error=str(exc))


def start_onnx_download(model_id: str) -> dict[str, object]:
    """
    开始下载 ONNX 向量模型到固定目录

    :param model_id: 模型 ID
    :return:
    """
    selected = (model_id or '').strip()
    if selected not in ONNX_EMBEDDING_MODELS:
        raise errors.RequestError(msg='ONNX 向量模型不在目录中')
    with _download_lock:
        if _download_state.status == 'downloading':
            raise errors.RequestError(msg='已有 ONNX 模型正在下载')
        downloaded = _is_onnx_model_downloaded(selected)
        _download_state.status = 'done' if downloaded else 'downloading'
        _download_state.progress = 1.0 if downloaded else 0.0
        _download_state.model_id = selected
        _download_state.error = None
    if downloaded:
        return get_onnx_download_status()
    threading.Thread(
        target=_run_onnx_download,
        args=(selected,),
        name='ai-buddy-onnx-download',
        daemon=True,
    ).start()
    return get_onnx_download_status()


def embed_onnx_texts(model_id: str, texts: Sequence[str]) -> list[list[float]]:
    """
    使用本地 ONNX / fastembed 生成文本向量

    :param model_id: fastembed 模型 ID
    :param texts: 文本列表
    :return:
    """
    if not texts:
        return []
    selected = require_onnx_model_downloaded(model_id)
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise errors.RequestError(msg='本地 ONNX 向量需要安装 fastembed') from exc
    global _engine, _engine_model
    with _engine_lock:
        if _engine is None or _engine_model != selected:
            try:
                _engine = TextEmbedding(model_name=selected, cache_dir=str(embedding_models_dir()))
                _engine_model = selected
            except Exception as exc:
                raise errors.RequestError(msg='本地 ONNX 向量模型加载失败，请确认已下载该模型') from exc
        engine = _engine
    vectors = list(engine.embed(list(texts)))
    return [[float(value) for value in vector] for vector in vectors]
