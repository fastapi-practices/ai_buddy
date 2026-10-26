from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import FileUnderstanding
from pydantic_ai.messages import (
    AudioUrl,
    DocumentUrl,
    ImageUrl,
    ModelMessage,
    ModelRequest,
    ToolReturnPart,
    UserPromptPart,
    VideoUrl,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.profiles import ModelProfile

from backend.common.exception import errors
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.models import auxiliary_model_name, bind_auxiliary_model
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType


def _reject_unsupported_remote_files(*, messages: Sequence[ModelMessage], profile: ModelProfile) -> None:
    """
    模型不支持直接读取远程文件时，拒绝仍以 URL 形式存在的附件

    :param messages: 本次请求的消息
    :param profile: 模型能力画像
    :return:
    """
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if not isinstance(part, (UserPromptPart, ToolReturnPart)):
                continue
            content = part.content if isinstance(part.content, list) else [part.content]
            for item in content:
                flag = (
                    'supports_image_input'
                    if isinstance(item, ImageUrl)
                    else 'supports_audio_file_input'
                    if isinstance(item, AudioUrl)
                    else 'supports_video_input'
                    if isinstance(item, VideoUrl)
                    else 'supports_document_input'
                    if isinstance(item, DocumentUrl)
                    else None
                )
                if flag and not profile.get(flag, False):
                    raise errors.RequestError(msg='文件理解仅接受已上传的附件，请先下载并上传远程文件')


@dataclass
class BuddyFileUnderstanding(FileUnderstanding[ChatAgentDeps]):
    """持久化 SDK 文件描述，跨轮与跨进程复用识别结果"""

    cache: dict[str, Any] = field(default_factory=dict)

    async def before_model_request(
        self, ctx: RunContext[ChatAgentDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        """恢复描述缓存并在模型请求前保存新增识别结果

        :param ctx: 运行上下文
        :param request_context: 模型请求上下文
        :return:
        """
        _reject_unsupported_remote_files(messages=request_context.messages, profile=request_context.model.profile)
        if self.cache:
            for index, message in enumerate(ctx.messages):
                if isinstance(message, ModelRequest):
                    metadata = deepcopy(message.metadata or {})
                    framework = metadata.setdefault('__pydantic_ai__', {})
                    framework['file_understanding'] = {
                        **self.cache,
                        **framework.get('file_understanding', {}),
                    }
                    ctx.messages[index] = replace(message, metadata=metadata)
                    break

        result = await super().before_model_request(ctx, request_context)
        cache = deepcopy(self.cache)
        for message in ctx.messages:
            if isinstance(message, ModelRequest):
                namespace = (message.metadata or {}).get('__pydantic_ai__', {}).get('file_understanding', {})
                for key, descriptions in namespace.items():
                    cache.setdefault(key, {}).update(descriptions)
        if cache != self.cache and ctx.deps.conversation_id:
            async with async_db_session.begin() as db:
                rows = await ai_buddy_message_dao.get_history_page(db, ctx.deps.conversation_id, before=None, limit=1)
                if rows and rows[0].role == 'assistant':
                    await ai_buddy_message_dao.update(
                        db,
                        rows[0].id,
                        {
                            'turn_context': {**(rows[0].turn_context or {}), 'file_understanding': cache},
                        },
                    )
            self.cache = cache
        return result


async def build_file_understanding_capability(ctx: CapabilityContext) -> CapabilityResult:
    """使用当前供应商中明确选择的模型解释附件

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    name = (ctx.forwarded_props.file_understanding_model or '').strip()
    if not name:
        return CapabilityResult(capability=None)
    model = await bind_auxiliary_model(ctx, auxiliary_model_name(ctx, name))
    cache = (
        await ai_buddy_message_dao.get_file_understanding_cache(ctx.db, ctx.conversation_id)
        if ctx.conversation_id
        else {}
    )
    return CapabilityResult(
        capability=BuddyFileUnderstanding(
            fallback_subagent_model=model,
            cache=cache,
            id=f'file-understanding-{ctx.forwarded_props.provider_id}-{model.model_name}',
        )
    )
