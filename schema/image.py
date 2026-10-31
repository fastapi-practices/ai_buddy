from typing import Literal

from pydantic import Field
from pydantic_ai.native_tools import ImageAspectRatio

from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.schema.chat_base import AIBuddyChatSchemaBase, AIBuddyRunAgentInput


class AIBuddyImageGenerationParam(AIBuddyChatSchemaBase):
    """生图参数，映射到 ImageGenerator"""

    background: Literal['transparent', 'opaque', 'auto'] | None = Field(
        None,
        description='背景类型，仅 OpenAI；transparent 仅支持 png/webp',
    )
    input_fidelity: Literal['high', 'low'] | None = Field(
        None,
        description='编辑时对输入图的保真度，仅 OpenAI，默认 low',
    )
    moderation: Literal['auto', 'low'] | None = Field(None, description='审核强度，仅 OpenAI')
    output_compression: int | None = Field(
        None,
        description='输出压缩，OpenAI jpeg/webp 默认 100',
    )
    output_format: Literal['png', 'webp', 'jpeg'] | None = Field(
        None,
        description='输出格式，仅 OpenAI，默认 png',
    )
    quality: Literal['low', 'medium', 'high', 'auto'] | None = Field(
        None,
        description='生成质量，仅 OpenAI',
    )
    size: str | None = Field(
        None,
        pattern=r'^(?:auto|512|1K|1\.5K|2K|3K|4K|[1-9][0-9]{2,4}x[1-9][0-9]{2,4})$',
        description='尺寸；支持分辨率档位或宽x高像素，Seedream 默认 2K，具体范围由模型决定',
    )
    aspect_ratio: ImageAspectRatio | None = Field(
        None,
        description='宽高比；Google/xAI 原样转发，OpenAI/Seedream 映射为 size',
    )


class AIBuddyImageForwardedPropsParam(AIBuddyImageGenerationParam):
    """生图扩展参数，与对话 forwarded_props 相互独立"""

    provider_id: int = Field(description='供应商 ID')
    model_id: str = Field(description='模型 ID')
    generation_type: Literal[AIBuddyChatGenerationType.image] = Field(
        default=AIBuddyChatGenerationType.image,
        description='生成类型',
    )


class AIBuddyImageCompletionParam(AIBuddyRunAgentInput):
    """AG-UI 生图运行请求"""

    forwarded_props: AIBuddyImageForwardedPropsParam = Field(description='生图扩展参数')
