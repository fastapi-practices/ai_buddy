import json
import math

from collections.abc import Mapping, Sequence
from typing import Any, assert_never, cast

from openai import APIConnectionError, APIStatusError
from openai.types.images_response import ImagesResponse
from pydantic_ai.exceptions import ContentFilterError, ModelAPIError, ModelHTTPError, UserError
from pydantic_ai.images import ImageGenerationInput, ImageGenerationResult, ImageGenerationSettings
from pydantic_ai.images._validation import validate_image_count, warn_image_generation_settings
from pydantic_ai.images.openai import OpenAIImageGenerationModel, OpenAIImageGenerationSettings
from pydantic_ai.messages import BinaryImage, ImageUrl, UploadedFile
from pydantic_ai.models import check_allow_model_requests
from pydantic_ai.models._decode_errors import map_decode_errors
from pydantic_ai.usage import RequestUsage


def is_seedream_model(model_name: str) -> bool:
    """
    判断是否使用 Seedream 生图协议适配

    :param model_name: 模型名称
    :return:
    """
    return model_name.strip().lower().startswith('doubao-seedream-')


def _resolve_seedream_size(
    settings: OpenAIImageGenerationSettings, extra_body: Mapping[str, Any]
) -> tuple[str, list[str]]:
    """
    把分辨率档位、宽高比和像素尺寸转换为火山 size

    :param settings: 生图设置
    :param extra_body: 额外请求参数
    :return:
    """
    size = settings.get('openai_size', extra_body.get('size', '2K'))
    size = '2K' if size is None or size == 'auto' else size
    if not isinstance(size, str):
        raise UserError('Seedream size 必须是分辨率档位或宽x高字符串')
    dimensions = settings.get('dimensions')
    aspect_ratio = settings.get('aspect_ratio')
    conflicts = ['dimensions'] if dimensions is not None and 'openai_size' in settings else []
    if dimensions is not None and 'openai_size' not in settings:
        return f'{dimensions[0]}x{dimensions[1]}', conflicts
    if aspect_ratio is None or 'x' in size:
        conflicts.extend(['aspect_ratio'] if aspect_ratio is not None else [])
        return size, conflicts

    resolution = {'1K': 1024, '1.5K': 1536, '2K': 2048, '3K': 3072, '4K': 4096}.get(size)
    if resolution is None:
        raise UserError('Seedream 使用 aspect_ratio 时，size 必须是 1K、1.5K、2K、3K 或 4K')
    try:
        width_ratio, height_ratio = (int(value) for value in aspect_ratio.split(':'))
    except (AttributeError, ValueError) as exc:
        raise UserError('Seedream aspect_ratio 必须是宽:高字符串') from exc
    if width_ratio <= 0 or height_ratio <= 0:
        raise UserError('Seedream aspect_ratio 的宽和高必须大于零')
    # 向下对齐 8 像素，避免舍入后超过分辨率档位的面积上限
    width = max(8, int(resolution * math.sqrt(width_ratio / height_ratio)) // 8 * 8)
    height = max(8, int(resolution * math.sqrt(height_ratio / width_ratio)) // 8 * 8)
    return f'{width}x{height}', conflicts


class SeedreamImageGenerationModel(OpenAIImageGenerationModel):
    """通过 OpenAI SDK 对接火山 Seedream 生图接口"""

    async def generate(
        self,
        prompt: str,
        *,
        images: Sequence[ImageGenerationInput] | None = None,
        settings: ImageGenerationSettings | None = None,
    ) -> ImageGenerationResult:
        """
        使用火山 JSON 生图请求生成或编辑图片

        :param prompt: 生图提示
        :param images: 参考图片
        :param settings: 生图设置
        :return:
        """
        check_allow_model_requests()
        prompt, images, settings = self.prepare_generate(prompt, images=images, settings=settings)
        openai_settings = cast('OpenAIImageGenerationSettings', settings)
        validate_image_count('Seedream', openai_settings.get('openai_n'))
        if openai_settings.get('openai_n') not in (None, 1):
            raise UserError('Seedream 不支持 openai_n，请通过 extra_body 配置 sequential_image_generation 组图参数')
        configured_body = openai_settings.get('extra_body')
        if configured_body is not None and not isinstance(configured_body, Mapping):
            raise UserError('Seedream extra_body 必须是 JSON 对象')
        extra_body: dict[str, Any] = dict(configured_body or {})
        size, conflicts = _resolve_seedream_size(openai_settings, extra_body)
        ignored = [
            key for key in openai_settings if key.startswith('openai_') and key not in {'openai_size', 'openai_n'}
        ]
        warn_image_generation_settings('Seedream', ignored=ignored, conflicts=conflicts)
        extra_body['size'] = size
        extra_body['response_format'] = 'b64_json'
        reference_images = self._map_reference_images(images)
        if reference_images:
            extra_body['image'] = reference_images[0] if len(reference_images) == 1 else reference_images

        try:
            with map_decode_errors(self.model_name):
                response = await self._client.images.generate(
                    prompt=prompt,
                    model=self.model_name,
                    extra_headers=openai_settings.get('extra_headers'),
                    extra_body=extra_body,
                )
        except APIStatusError as exc:
            if exc.status_code >= 400:
                if isinstance(exc.body, dict) and exc.body.get('code') == 'moderation_blocked':
                    raise ContentFilterError('Seedream 生图请求被内容审核拦截', json.dumps(exc.body)) from exc
                raise ModelHTTPError(
                    status_code=exc.status_code,
                    model_name=self.model_name,
                    body=exc.body,
                    headers=dict(exc.response.headers),
                ) from exc
            raise
        except APIConnectionError as exc:
            raise ModelAPIError(model_name=self.model_name, message=exc.message) from exc

        return self._map_response(prompt, response)

    def _map_reference_images(self, images: Sequence[ImageGenerationInput]) -> list[str]:
        """
        将 SDK 参考图转为火山接受的 URL 或 Data URI

        :param images: 参考图片
        :return:
        """
        reference_images: list[str] = []
        for image in images:
            if isinstance(image, UploadedFile):
                self._validate_uploaded_file_provider(image)
                raise UserError('Seedream 不支持 UploadedFile.file_id 参考图，请使用 BinaryImage 或 ImageUrl')
            if isinstance(image, ImageUrl):
                reference_images.append(image.url)
            elif isinstance(image, BinaryImage):
                reference_images.append(image.data_uri)
            else:
                assert_never(image)
        return reference_images

    def _map_response(self, prompt: str, response: ImagesResponse) -> ImageGenerationResult:
        """
        复用 SDK 图片解析并保留火山实际返回的用量

        :param prompt: 生图提示
        :param response: 火山生图响应
        :return:
        """
        # 火山未返回 OpenAI 必填的 input_tokens_details，图片解析与用量转换独立处理
        result = super()._map_response(prompt, response.model_copy(update={'usage': None}))
        if response.usage is None:
            return result
        usage_data = response.usage.model_dump(exclude_none=True)
        details: dict[str, int] = {}
        for key in ('total_tokens', 'generated_images', 'input_images'):
            value = usage_data.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                details[key] = value
        tool_usage = usage_data.get('tool_usage')
        if isinstance(tool_usage, dict):
            for key, value in tool_usage.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    details[f'tool_usage_{key}'] = value
        input_tokens = usage_data.get('input_tokens')
        output_tokens = usage_data.get('output_tokens')
        result.usage = RequestUsage(
            input_tokens=input_tokens if isinstance(input_tokens, int) and not isinstance(input_tokens, bool) else 0,
            output_tokens=output_tokens
            if isinstance(output_tokens, int) and not isinstance(output_tokens, bool)
            else 0,
            details=details,
        )
        return result
