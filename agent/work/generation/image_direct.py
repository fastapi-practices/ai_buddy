from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic_ai import BinaryImage, FilePart, ImageGenerator, ImageUrl, ModelRequest, RunContext, UserPromptPart
from pydantic_ai.images import ImageGenerationInput, ImageGenerationModel, ImageGenerationSettings
from pydantic_ai.images.openai import OpenAIImageGenerationSettings
from pydantic_ai.messages import BinaryContent, ModelMessage, ModelResponse, ModelResponseStreamEvent, UploadedFile
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.settings import ModelSettings

from backend.common.exception import errors
from backend.plugin.ai_buddy.enums import AIBuddyProviderType
from backend.plugin.ai_buddy.provider.seedream import is_seedream_model
from backend.plugin.ai_buddy.schema.image import AIBuddyImageForwardedPropsParam
from backend.plugin.ai_buddy.security.jev import jev_enabled, jev_input_ok

_GOOGLE_IMAGE_SIZES: frozenset[str] = frozenset({'512', '1K', '2K', '4K'})
_XAI_RESOLUTION_BY_SIZE: dict[str, str] = {'1K': '1k', '2K': '2k'}
_OPENAI_IMAGE_SETTING_FIELDS: tuple[tuple[str, str], ...] = (
    ('size', 'openai_size'),
    ('quality', 'openai_quality'),
    ('output_format', 'openai_output_format'),
    ('background', 'openai_background'),
    ('moderation', 'openai_moderation'),
    ('input_fidelity', 'openai_input_fidelity'),
    ('output_compression', 'openai_output_compression'),
)
_OPENAI_GPT_IMAGE_1_MODELS: tuple[str, ...] = ('gpt-image-1', 'gpt-image-1.5')
_OPENAI_GPT_IMAGE_1_ASPECT_RATIO_TO_SIZE: dict[str, str] = {
    '1:1': '1024x1024',
    '2:3': '1024x1536',
    '3:2': '1536x1024',
}
_OPENAI_GPT_IMAGE_2_ASPECT_RATIO_TO_SIZE: dict[str, str] = {
    '1:1': '1024x1024',
    '2:3': '832x1248',
    '3:2': '1248x832',
    '3:4': '864x1152',
    '4:3': '1152x864',
    '4:5': '896x1120',
    '5:4': '1120x896',
    '9:16': '720x1280',
    '16:9': '1280x720',
    '21:9': '1568x672',
}


def extract_image_prompt_and_references(messages: Sequence[ModelMessage]) -> tuple[str, list[ImageGenerationInput]]:
    """
    从当前轮用户消息提取生图提示和参考图

    :param messages: 模型消息列表
    :return:
    """
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        user_part = next((part for part in reversed(message.parts) if isinstance(part, UserPromptPart)), None)
        if user_part is None:
            continue
        content_items = [user_part.content] if isinstance(user_part.content, str) else list(user_part.content)
        prompt_parts = [' '.join(item.split()) for item in content_items if isinstance(item, str) and item.split()]
        references: list[ImageGenerationInput] = []
        for item in content_items:
            if isinstance(item, BinaryImage | ImageUrl | UploadedFile):
                references.append(item)
            elif isinstance(item, BinaryContent) and item.is_image:
                references.append(BinaryImage(data=item.data, media_type=item.media_type))
        prompt = ' '.join(prompt_parts)
        if not prompt:
            raise errors.RequestError(msg='当前轮生图提示不能为空')
        return prompt, references
    raise errors.RequestError(msg='最后一条消息必须是用户消息')


def build_direct_image_generation_settings(
    *,
    provider_type: int | AIBuddyProviderType,
    forwarded_props: AIBuddyImageForwardedPropsParam,
) -> ImageGenerationSettings:
    """
    把客户端生图参数映射为 ImageGenerator 设置

    :param provider_type: 供应商类型
    :param forwarded_props: 生图扩展参数
    :return:
    """
    provider = AIBuddyProviderType(provider_type)
    settings: dict[str, Any] = {}
    if provider in {AIBuddyProviderType.openai, AIBuddyProviderType.openai_responses}:
        if is_seedream_model(forwarded_props.model_id):
            settings['openai_size'] = '2K' if forwarded_props.size in {None, 'auto'} else forwarded_props.size
            settings.update(forwarded_props.model_dump(include={'aspect_ratio'}, exclude_none=True))
            return OpenAIImageGenerationSettings(**settings)
        for source, target in _OPENAI_IMAGE_SETTING_FIELDS:
            value = getattr(forwarded_props, source)
            if value is not None:
                settings[target] = value
        if 'openai_size' not in settings and forwarded_props.aspect_ratio is not None:
            # OpenAI 无原生宽高比，Pydantic AI 也不识别 gpt-image-2.5 等新模型名
            name = forwarded_props.model_id.lower()
            is_gpt_image_1 = any(name == item or name.startswith(f'{item}-') for item in _OPENAI_GPT_IMAGE_1_MODELS)
            mapping = (
                _OPENAI_GPT_IMAGE_1_ASPECT_RATIO_TO_SIZE if is_gpt_image_1 else _OPENAI_GPT_IMAGE_2_ASPECT_RATIO_TO_SIZE
            )
            mapped_size = mapping.get(forwarded_props.aspect_ratio)
            if mapped_size is None:
                supported = '、'.join(mapping)
                raise errors.RequestError(
                    msg=f'当前 OpenAI 生图模型不支持宽高比 {forwarded_props.aspect_ratio}，可选：{supported}'
                )
            settings['openai_size'] = mapped_size
        return OpenAIImageGenerationSettings(**settings)
    if forwarded_props.aspect_ratio is not None:
        settings['aspect_ratio'] = forwarded_props.aspect_ratio
    if provider == AIBuddyProviderType.google and forwarded_props.size in _GOOGLE_IMAGE_SIZES:
        settings['google_image_config'] = {'image_size': forwarded_props.size}
    resolution = _XAI_RESOLUTION_BY_SIZE.get(forwarded_props.size or '')
    if provider == AIBuddyProviderType.xai and resolution is not None:
        settings['xai_resolution'] = resolution
    return settings


@dataclass
class DirectImageGenerationStreamedResponse(StreamedResponse):
    """把一次 ImageGenerator 结果重放为 Agent 流式事件"""

    _model_name: str
    _provider_name: str
    _response: ModelResponse
    _timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """从已生成的图像响应初始化用量"""
        self._usage = self._response.usage

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        """逐个抛出已生成的图片部件"""
        for index, part in enumerate(self._response.parts):
            yield self._parts_manager.handle_part(vendor_part_id=index, part=part)

    @property
    def model_name(self) -> str:
        """生图模型名称"""
        return self._model_name

    @property
    def provider_name(self) -> str:
        """供应商名称"""
        return self._provider_name

    @property
    def provider_url(self) -> str | None:
        """供应商地址"""
        return self._response.provider_url

    @property
    def timestamp(self) -> datetime:
        """响应时间"""
        return self._timestamp

    @staticmethod
    async def close_stream() -> None:
        """关闭流，独立生图无长连接"""
        return


class DirectImageGenerationModel(Model):
    """把 ImageGenerator 接到对话 Agent 接口，沿用对话流和落库"""

    def __init__(
        self,
        image_model: ImageGenerationModel,
        *,
        settings: ImageGenerationSettings | None = None,
    ) -> None:
        """
        初始化独立生图模型适配器

        :param image_model: Pydantic AI 生图模型
        :param settings: 默认 ImageGenerator 设置
        :return:
        """
        self._image_model = image_model
        self._generator = ImageGenerator(image_model, settings=settings, defer_model_check=False)
        super().__init__(profile=ModelProfile(supports_image_output=True, supports_tools=False))

    def configure(self, *, settings: ImageGenerationSettings | None) -> None:
        """
        按本轮客户端参数重建生成器

        :param settings: ImageGenerator 设置
        :return:
        """
        self._generator = ImageGenerator(self._image_model, settings=settings, defer_model_check=False)

    @property
    def model_name(self) -> str:
        """生图模型名称"""
        return self._image_model.model_name

    @property
    def system(self) -> str:
        """供应商标识"""
        return self._image_model.system

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """
        执行一次非流式生图

        :param messages: 模型消息列表
        :param model_settings: 对话模型设置，独立生图不使用
        :param model_request_parameters: 请求参数
        :return:
        """
        _model_settings, model_request_parameters = self.prepare_request(model_settings, model_request_parameters)
        return await self._generate_response(messages)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse, None]:
        """
        执行一次生图并以流事件重放结果

        :param messages: 模型消息列表
        :param model_settings: 对话模型设置，独立生图不使用
        :param model_request_parameters: 请求参数
        :param run_context: 运行上下文，独立生图不使用
        :return:
        """
        _model_settings, model_request_parameters = self.prepare_request(model_settings, model_request_parameters)
        response = await self._generate_response(messages)
        yield DirectImageGenerationStreamedResponse(
            model_request_parameters=model_request_parameters,
            _model_name=self.model_name,
            _provider_name=self.system,
            _response=response,
        )

    async def _generate_response(self, messages: list[ModelMessage]) -> ModelResponse:
        """
        调用 ImageGenerator 并组装模型响应

        :param messages: 模型消息列表
        :return:
        """
        prompt, references = extract_image_prompt_and_references(messages)
        if jev_enabled():
            verdict = await jev_input_ok(prompt)
            if verdict.action == 'block':
                raise errors.RequestError(msg=verdict.message or '请求被安全策略拒绝')

        result = await self._generator.generate(prompt, images=references or None)

        usage = result.usage
        if usage.cost is None:
            try:
                usage.cost = result.cost().total_price
            except LookupError:
                pass
        return ModelResponse(
            parts=[
                FilePart(
                    content=image.content,
                    provider_name=result.provider_name,
                    provider_details=image.provider_details,
                )
                for image in result.images
            ],
            usage=usage,
            model_name=result.model_name,
            timestamp=result.timestamp,
            provider_name=result.provider_name,
            provider_url=result.provider_url,
            provider_response_id=result.provider_response_id,
            provider_details=result.provider_details,
        )
