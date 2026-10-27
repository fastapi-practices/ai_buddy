import json

from backend.common.exception import errors
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.coding.sandbox import resolve_sandbox_path
from backend.plugin.ai_buddy.agent.coding.types import AgentRunContext
from backend.plugin.ai_buddy.enums import AIBuddyArtifactKind
from backend.plugin.ai_buddy.service.artifact_service import ai_buddy_artifact_service

_EXCLUDED_PARTS = frozenset({'.git', 'node_modules', '.venv', '__pycache__', '.fba', 'inbound'})


async def deliver_sandbox_file(
    *, ctx: AgentRunContext, path: str, title: str | None, kind: AIBuddyArtifactKind | None
) -> str:
    """把服务端沙箱中的文件交付为持久产物，沙箱被回收后聊天记录仍可回显和下载

    :param ctx: 运行上下文
    :param path: 沙箱工作区内的文件路径
    :param title: 产物标题，为空使用文件名
    :param kind: 产物类型，为空按媒体类型推断
    :return:
    """
    if ctx.sandbox is None:
        raise errors.RequestError(msg='当前运行没有可交付的工作区')
    target = resolve_sandbox_path(path)
    if _EXCLUDED_PARTS.intersection(target.split('/')):
        raise errors.RequestError(msg='依赖目录和内部文件不能交付')
    data = await ctx.sandbox.read_bytes(path=target, max_bytes=settings.S3_UPLOAD_SIZE_MAX)
    async with async_db_session.begin() as db:
        artifact = await ai_buddy_artifact_service.deliver_file(
            db=db,
            user_id=ctx.user_id,
            conversation_id=ctx.conversation_id,
            filename=target.rsplit('/', 1)[-1],
            data=data,
            title=title,
            kind=kind,
        )
        return json.dumps(
            {
                'artifact_id': artifact.id,
                'title': artifact.title,
                'kind': artifact.kind,
                'size': artifact.size,
                'sha256': artifact.sha256,
                'mime_type': artifact.mime_type,
            },
            ensure_ascii=False,
        )
