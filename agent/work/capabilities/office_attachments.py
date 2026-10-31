import asyncio
import hashlib

from dataclasses import replace

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import BinaryContent, ModelMessage, ModelRequest, UserContent, UserPromptPart
from pydantic_ai.models import ModelRequestContext

from backend.common.log import log
from backend.plugin.ai_buddy.agent.work.capabilities.sandbox_tools import sandbox_tools_enabled
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.utils.office_text import input_attachments, is_office_media_type, office_to_markdown

_INLINE_CHARS = 30000
# 沙箱可用时只内联预览，完整内容由模型导入沙箱后用脚本处理，避免多份大附件撑满上下文
_INLINE_CHARS_WITH_SANDBOX = 12000


class OfficeAttachments(AbstractCapability[ChatAgentDeps]):
    """把 Word、Excel、PowerPoint 附件在本次模型请求中转为文本，持久化的原始消息不改写"""

    def __init__(self, *, sandbox: bool) -> None:
        """
        创建附件转换能力

        :param sandbox: 本轮是否装配了沙箱工具
        :return:
        """
        self._sandbox = sandbox
        self._cache: dict[str, str | None] = {}

    async def before_model_request(
        self, ctx: RunContext[ChatAgentDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        """
        模型请求前改写用户消息中的附件

        :param ctx: 运行上下文
        :param request_context: 模型请求上下文
        :return:
        """
        del ctx
        if not input_attachments(request_context.messages):
            return request_context
        messages = [await self._rewrite(message) for message in request_context.messages]
        return replace(request_context, messages=messages)

    async def _rewrite(self, message: ModelMessage) -> ModelMessage:
        """
        改写一条请求消息中的附件，其余消息原样返回

        :param message: 模型消息
        :return:
        """
        if not isinstance(message, ModelRequest):
            return message
        parts = []
        for part in message.parts:
            if not isinstance(part, UserPromptPart) or isinstance(part.content, str):
                parts.append(part)
                continue
            content: list[UserContent] = []
            for item in part.content:
                content.extend(await self._expand(item))
            parts.append(replace(part, content=content))
        return replace(message, parts=parts)

    async def _expand(self, item: UserContent) -> list[UserContent]:
        """
        Office 附件转为文本，沙箱可用时为其余文档类附件补充导入说明

        :param item: 用户消息内容项
        :return:
        """
        if not isinstance(item, BinaryContent):
            return [item]
        if is_office_media_type(item.media_type):
            return [await self._office_text(item)]
        if self._sandbox and not (item.is_image or item.is_audio or item.is_video):
            return [item, self._describe(item)]
        return [item]

    async def _office_text(self, item: BinaryContent) -> str:
        """
        转换 Office 附件，同一内容在本轮只转换一次

        :param item: Office 附件
        :return:
        """
        digest = hashlib.sha256(item.data).hexdigest()
        if digest not in self._cache:
            try:
                self._cache[digest] = await asyncio.to_thread(office_to_markdown, item.data, item.media_type)
            except Exception as exc:
                log.warning(f'Office 附件解析失败 type={item.media_type}: {type(exc).__name__}')
                self._cache[digest] = None
        markdown = self._cache[digest]
        if markdown is None:
            return f'{self._describe(item)}\n\n无法解析该文件，可能已损坏或已加密'
        limit = _INLINE_CHARS_WITH_SANDBOX if self._sandbox else _INLINE_CHARS
        if len(markdown) <= limit:
            return f'{self._describe(item)}\n\n{markdown}'
        hint = '，完整文件请先导入沙箱后用脚本处理' if self._sandbox else ''
        preview = markdown[:limit].rsplit('\n', 1)[0]
        return f'{self._describe(item)}\n\n{preview}\n\n…内容已截断，共 {len(markdown)} 字符{hint}'

    def _describe(self, item: BinaryContent) -> str:
        """
        生成附件说明，沙箱可用时带上导入所需的内容摘要前缀

        :param item: 附件
        :return:
        """
        text = f'用户附件「{item.identifier}」（{item.media_type}，{len(item.data)} 字节'
        if not self._sandbox:
            return f'{text}）'
        digest = hashlib.sha256(item.data).hexdigest()[:12]
        return f'{text}，sha256 前缀 {digest}，可用 import_attachment 导入沙箱）'


def build_office_attachments_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    让不支持直接读取 Office 文件的模型也能读懂附件内容

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    return CapabilityResult(capability=OfficeAttachments(sandbox=sandbox_tools_enabled(ctx)))
