from typing import Any

from pydantic_ai.models import Model

from backend.common.exception import errors
from backend.plugin.ai_buddy.enums import (
    AIBuddyModelCapability,
    AIBuddyModelKind,
    AIBuddyModelModality,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.model import AIBuddyModel
from backend.plugin.ai_buddy.schema.model import CreateAIBuddyModelParam, UpdateAIBuddyModelParam
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID

_EMBEDDING_PROVIDER_TYPES = frozenset({
    AIBuddyProviderType.openai,
    AIBuddyProviderType.openai_responses,
    AIBuddyProviderType.openrouter,
})
_IMAGE_PROVIDER_TYPES = frozenset({
    AIBuddyProviderType.google,
    AIBuddyProviderType.openai,
    AIBuddyProviderType.openai_responses,
    AIBuddyProviderType.xai,
})
_DEFAULT_KIND_ERROR = {
    AIBuddyModelKind.chat: '默认对话模型必须是对话模型',
    AIBuddyModelKind.embedding: '默认向量模型必须是向量模型',
    AIBuddyModelKind.image: '默认绘画模型必须是图片模型',
}
_DEFAULT_INPUT_MODALITIES: dict[AIBuddyModelKind, list[AIBuddyModelModality]] = {
    AIBuddyModelKind.chat: [AIBuddyModelModality.text],
    AIBuddyModelKind.embedding: [AIBuddyModelModality.text],
    AIBuddyModelKind.image: [AIBuddyModelModality.text],
}


def _normalize_model_name(name: str | None, model_id: str) -> str:
    """
    模型名称为空时回退到模型 ID

    :param name: 模型名称
    :param model_id: 模型 ID
    :return:
    """
    normalized = (name or '').strip()
    return normalized or model_id.strip()


def normalize_model_param(
    obj: CreateAIBuddyModelParam | UpdateAIBuddyModelParam,
) -> CreateAIBuddyModelParam | UpdateAIBuddyModelParam:
    """
    规范化模型写入参数

    :param obj: 创建或更新参数
    :return:
    """
    return obj.model_copy(
        update={
            'name': _normalize_model_name(obj.name, obj.model_id),
            'capabilities': normalize_capabilities(obj.capabilities),
            'input_modalities': (
                _normalize_modalities(obj.input_modalities)
                if obj.input_modalities is not None
                else list(_DEFAULT_INPUT_MODALITIES[obj.kind])
            ),
        }
    )


def _normalize_modalities(values: list[AIBuddyModelModality] | list[str]) -> list[AIBuddyModelModality]:
    """
    去重并按固定顺序排列模态

    :param values: 待处理值列表
    :return:
    """
    selected = set(values)
    return [item for item in AIBuddyModelModality if item in selected]


def normalize_capabilities(values: list[AIBuddyModelCapability] | list[str] | None) -> list[AIBuddyModelCapability]:
    """
    规范化模型能力列表，去重并按固定顺序排列

    :param values: 原始能力列表
    :return:
    """
    if not values:
        return []
    valid = {item.value: item for item in AIBuddyModelCapability}
    selected: set[AIBuddyModelCapability] = set()
    for item in values:
        key = item.value if isinstance(item, AIBuddyModelCapability) else str(item)
        capability = valid.get(key)
        if capability is not None:
            selected.add(capability)
    return [item for item in AIBuddyModelCapability if item in selected]


def parse_model_capabilities(raw: Any) -> list[AIBuddyModelCapability]:
    """
    解析模型记录上的能力列表

    :param raw: 数据库或快照中的能力值
    :return:
    """
    if not isinstance(raw, list):
        return []
    return normalize_capabilities(raw)


def has_model_capability(model: AIBuddyModel, capability: AIBuddyModelCapability) -> bool:
    """
    判断模型是否声明了指定能力

    :param model: 模型
    :param capability: 模型能力
    :return:
    """
    return capability in parse_model_capabilities(model.capabilities)


def validate_model_binding(*, kind: AIBuddyModelKind, provider_type: int) -> None:
    """
    校验供应商是否支持配置的模型类型

    :param kind: 模型类型
    :param provider_type: 供应商类型
    :return:
    """
    if kind == AIBuddyModelKind.embedding and provider_type not in _EMBEDDING_PROVIDER_TYPES:
        raise errors.RequestError(msg='当前供应商不支持向量模型调用')
    if kind == AIBuddyModelKind.image and provider_type not in _IMAGE_PROVIDER_TYPES:
        raise errors.RequestError(msg='当前供应商不支持独立图片生成')


def _kind_matches_model(kind: AIBuddyModelKind, model: AIBuddyModel) -> bool:
    """
    判断模型类型是否匹配默认类型

    :param kind: 模型类型
    :param model: 模型
    :return:
    """
    try:
        return AIBuddyModelKind(model.kind) == kind
    except ValueError:
        return False


def eligible_for_default(*, kind: AIBuddyModelKind, provider: Any, model: AIBuddyModel) -> bool:
    """
    判断平台模型是否可被当前运行时用作指定默认模型

    :param kind: 模型类型
    :param provider: 供应商对象
    :param model: 模型对象
    :return:
    """
    if (
        kind not in _DEFAULT_KIND_ERROR
        or not _kind_matches_model(kind, model)
        or provider.user_id != SYSTEM_OWNER_USER_ID
        or provider.status != 1
        or model.status != 1
    ):
        return False
    input_modalities = set(model.input_modalities or [])
    if AIBuddyModelModality.text not in input_modalities:
        return False
    if kind == AIBuddyModelKind.chat:
        return True
    if kind == AIBuddyModelKind.embedding:
        return provider.type in _EMBEDDING_PROVIDER_TYPES
    return provider.type in _IMAGE_PROVIDER_TYPES


def require_default_kind(kind: AIBuddyModelKind, model: AIBuddyModel) -> None:
    """
    校验默认模型类型与所选模型一致

    :param kind: 模型类型
    :param model: 模型
    :return:
    """
    if not _kind_matches_model(kind, model):
        raise errors.RequestError(msg=_DEFAULT_KIND_ERROR[kind])


def require_model_kind(model: AIBuddyModel, kind: AIBuddyModelKind, *, msg: str) -> None:
    """
    校验模型类型

    :param model: 模型
    :param kind: 期望类型
    :param msg: 不匹配时的错误信息
    :return:
    """
    if not _kind_matches_model(kind, model):
        raise errors.RequestError(msg=msg)


def apply_catalog_profile(*, model: Model, input_modalities: list[str] | None, context_window: int | None) -> None:
    """
    将用户配置或目录同步的输入能力应用到运行模型

    :param model: SDK 模型实例
    :param input_modalities: 已保存的输入模态
    :param context_window: 已保存的上下文窗口
    :return:
    """
    modalities = set(input_modalities or ['text'])
    model.profile.update(
        supports_image_input='image' in modalities,
        supports_document_input='pdf' in modalities,
        supports_audio_file_input='audio' in modalities,
        supports_video_input='video' in modalities,
        context_window=context_window,
    )
