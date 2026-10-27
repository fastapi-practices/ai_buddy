import base64

from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

from openai.types.images_response import ImagesResponse
from pydantic_ai.images import ImageGenerationInput, ImageGenerationResult, ImageGenerationSettings
from pydantic_ai.images.openai import OpenAIImageGenerationModel
from pydantic_ai.messages import ImageUrl
from pydantic_ai.models import download_item

if TYPE_CHECKING:
    from openai.types.image import Image


class _UrlOnlyImageResponse(Exception):  # ruff: ignore[error-suffix-on-exception-name]
    """图片响应只有 url 没有 b64_json，需要异步下载后重新解析"""

    def __init__(self, prompt: str, response: ImagesResponse) -> None:
        """
        保存图片生成提示与原始响应

        :param prompt: 提示内容
        :param response: 原始响应
        :return:
        """
        super().__init__('image response contains url only')
        self.prompt = prompt
        self.response = response


class OpenAICompatibleImageGenerationModel(OpenAIImageGenerationModel):
    """兼容只返回图片 url 的 OpenAI 兼容网关

    SDK 只解析 b64_json，部分网关（或非 gpt-image 模型）按 url 返回，
    此时下载图片并转换为 b64_json 后复用 SDK 解析
    """

    async def generate(
        self,
        prompt: str,
        *,
        images: Sequence[ImageGenerationInput] | None = None,
        settings: ImageGenerationSettings | None = None,
    ) -> ImageGenerationResult:
        """
        生成或编辑图片，响应仅含 url 时下载图片兜底

        :param prompt: 生图提示
        :param images: 参考图片
        :param settings: 生图设置
        :return:
        """
        try:
            return await super().generate(prompt, images=images, settings=settings)
        except _UrlOnlyImageResponse as exc:
            data: list[Image] = []
            for item in exc.response.data or []:
                if item.b64_json or not item.url:
                    data.append(item)
                    continue
                downloaded = await download_item(ImageUrl(url=item.url), data_format='bytes')
                data.append(item.model_copy(update={'b64_json': base64.b64encode(downloaded['data']).decode()}))
            return super()._map_response(exc.prompt, exc.response.model_copy(update={'data': data}))

    def _map_response(self, prompt: str, response: ImagesResponse) -> ImageGenerationResult:
        """
        解析响应，遇到仅含 url 的图片时交给 generate 下载

        :param prompt: 生图提示
        :param response: 生图响应
        :return:
        """
        if any(not item.b64_json and item.url for item in cast('list[Image]', response.data or [])):
            raise _UrlOnlyImageResponse(prompt, response)
        return self._drop_empty_usage_details(super()._map_response(prompt, response))

    @staticmethod
    def _drop_empty_usage_details(result: ImageGenerationResult) -> ImageGenerationResult:
        """
        移除网关返回 null 的用量明细，SDK 会把它们原样写入 details，导致后续整数校验失败

        :param result: 生图结果
        :return:
        """
        result.usage.details = {k: v for k, v in result.usage.details.items() if isinstance(v, int)}
        return result
