from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.core.conf import settings
from backend.plugin.ai_buddy.enums import (
    AIBuddyDocumentExtractBackend,
    AIBuddyEmbeddingBackend,
    AIBuddyExecutionBackend,
    AIBuddyOcrBackend,
)
from backend.plugin.core import check_plugin_installed
from backend.utils.dynamic_config import load_config
from backend.utils.serializers import select_list_serialize

_AI_CONFIG_KEYS: tuple[str, ...] = (
    'AI_BUDDY_EXA_API_KEY',
    'AI_BUDDY_TAVILY_API_KEY',
    'AI_BUDDY_TYPESAFE_API_KEY',
)


def _non_negative_int(value: str) -> int:
    """
    将配置值转为非负整数

    :param value: 配置原文
    :return:
    """
    text = (value or '').strip()
    if not text:
        return 0
    try:
        return max(0, int(text))
    except ValueError:
        return 0


def _positive_int(value: str) -> int:
    """
    将配置值转为正整数

    :param value: 配置原文
    :return:
    """
    return max(1, _non_negative_int(value))


def _jev_model(value: str) -> str:
    """
    将配置值转为 Jev 模型 ID

    :param value: 配置原文
    :return:
    """
    return (value or '').strip() or 'jev-latest'


def _unit_interval(value: str) -> float:
    """
    将配置值转为 0 到 1 的概率阈值

    :param value: 配置原文
    :return:
    """
    text = (value or '').strip()
    if not text:
        return 0.75
    try:
        number = float(text)
    except ValueError:
        return 0.75
    return min(1.0, max(0.0, number))


def _document_extract_backend(value: str) -> str:
    """
    将配置值转为文档抽取后端

    :param value: 配置原文
    :return:
    """
    text = (value or '').strip().lower()
    try:
        return AIBuddyDocumentExtractBackend(text).value
    except ValueError:
        return AIBuddyDocumentExtractBackend.native.value


def _embedding_backend(value: str) -> str:
    """
    将向量化方式解析为 remote 或 onnx

    :param value: 配置原文
    :return:
    """
    text = (value or '').strip().lower()
    try:
        return AIBuddyEmbeddingBackend(text).value
    except ValueError:
        return AIBuddyEmbeddingBackend.remote.value


def _ocr_backend(value: str) -> str:
    """
    将配置值转为 OCR 后端

    :param value: 配置原文
    :return:
    """
    text = (value or '').strip().lower()
    try:
        return AIBuddyOcrBackend(text).value
    except ValueError as exc:
        raise ValueError('OCR 后端配置无效') from exc


def _execution_backend(value: str) -> str:
    """
    校验默认执行后端，未知值使用本机并要求桌面连接

    :param value: 配置原文
    :return:
    """
    text = (value or '').strip().lower()
    try:
        return AIBuddyExecutionBackend(text).value
    except ValueError:
        return AIBuddyExecutionBackend.local.value


_AI_CONFIG_MAPPING: dict[str, Callable[[str], object]] = {
    'AI_BUDDY_AGENT_EXECUTION_BACKEND': _execution_backend,
    'AI_BUDDY_EXA_API_KEY': str,
    'AI_BUDDY_TAVILY_API_KEY': str,
    'AI_BUDDY_TYPESAFE_API_KEY': str,
    'AI_BUDDY_HTTP_MAX_RETRIES': _non_negative_int,
    'AI_BUDDY_MCP_MAX_RETRIES': _non_negative_int,
    'AI_BUDDY_COMPACTION_KEEP_MESSAGES': _positive_int,
    'AI_BUDDY_COMPACTION_MAX_MESSAGES': _positive_int,
    'AI_BUDDY_DOCUMENT_EXTRACT_BACKEND': _document_extract_backend,
    'AI_BUDDY_UNSTRUCTURED_API_URL': str,
    'AI_BUDDY_UNSTRUCTURED_API_KEY': str,
    'AI_BUDDY_MARKITDOWN_DOCINTEL_ENDPOINT': str,
    'AI_BUDDY_MARKITDOWN_DOCINTEL_API_KEY': str,
    'AI_BUDDY_MINERU_API_KEY': str,
    'AI_BUDDY_OPEN_MINERU_API_URL': str,
    'AI_BUDDY_OPEN_MINERU_API_KEY': str,
    'AI_BUDDY_DOC2X_API_URL': str,
    'AI_BUDDY_DOC2X_API_KEY': str,
    'AI_BUDDY_MISTRAL_API_URL': str,
    'AI_BUDDY_MISTRAL_API_KEY': str,
    'AI_BUDDY_EMBEDDING_BACKEND': _embedding_backend,
    'AI_BUDDY_ONNX_EMBEDDING_MODEL': str,
    'AI_BUDDY_OCR_BACKEND': _ocr_backend,
    'AI_BUDDY_PADDLEOCR_API_URL': str,
    'AI_BUDDY_RAG_CHUNK_CHARS': _positive_int,
    'AI_BUDDY_RAG_CHUNK_OVERLAP': _non_negative_int,
    'AI_BUDDY_RAG_TOP_K': _positive_int,
    'AI_BUDDY_JEV_MODEL': _jev_model,
    'AI_BUDDY_JEV_INPUT_THRESHOLD': _unit_interval,
}


async def load_ai_buddy_config(db: AsyncSession, *, reindex_on_change: bool = True) -> None:
    """
    获取 AI 配置

    :param db: 数据库会话
    :param reindex_on_change: 是否检测全局向量配置变更并调度重建
    :return:
    """
    if not check_plugin_installed('config'):
        return
    await load_config(db, 'ai', _AI_CONFIG_MAPPING, 'AI_BUDDY_CONFIG_STATUS')
    if not reindex_on_change:
        return
    from backend.database.redis import redis_client
    from backend.plugin.ai_buddy.service.knowledge_service import ai_buddy_knowledge_service

    fingerprint_key = f'{settings.PLUGIN_REDIS_PREFIX}:ai_buddy:embed-fp'
    fingerprint = settings.AI_BUDDY_EMBEDDING_BACKEND
    if fingerprint == AIBuddyEmbeddingBackend.onnx:
        fingerprint += f'|{settings.AI_BUDDY_ONNX_EMBEDDING_MODEL.strip()}'
    stored = await redis_client.get(fingerprint_key)
    if stored is not None and stored.startswith(f'{AIBuddyEmbeddingBackend.remote.value}|'):
        stored = AIBuddyEmbeddingBackend.remote.value
    await redis_client.set(fingerprint_key, fingerprint)
    if stored is not None and stored != fingerprint:
        ai_buddy_knowledge_service.schedule_reindex()


async def get_ai_buddy_config_snapshot(db: AsyncSession) -> tuple[StatusType, dict[str, str]]:
    """
    读取 AI 配置整体状态和密钥原文

    :param db: 数据库会话
    :return:
    """
    values = {key: getattr(settings, key, '') for key in _AI_CONFIG_KEYS}
    if not check_plugin_installed('config'):
        return StatusType.enable, values
    try:
        from backend.plugin.config.enums import ConfigType
        from backend.plugin.config.service.config_service import config_service
    except ImportError as e:
        raise ImportError('参数配置插件用法导入失败，请联系系统管理员') from e

    dynamic_config = await config_service.get_all(db=db, type=ConfigType.ai)
    configs: dict[str, str] = {}
    if dynamic_config:
        rows = [item for item in dynamic_config if item is not None]
        if rows:
            config_list = select_list_serialize(rows) if hasattr(rows[0], '__table__') else rows
            configs = {str(item['key']): item.get('value') or '' for item in config_list}
    status = StatusType.disable if configs.get('AI_BUDDY_CONFIG_STATUS', '1') == '0' else StatusType.enable
    for key in _AI_CONFIG_KEYS:
        if key in configs:
            values[key] = configs[key]
    return status, values
