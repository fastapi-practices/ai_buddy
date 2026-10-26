from pydantic_ai.capabilities import Capability

from backend.common.exception import errors
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.service.artifact_service import ai_buddy_artifact_service
from backend.plugin.ai_buddy.service.knowledge_service import ai_buddy_knowledge_service


async def build_workspace_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    将工作区引用注入为当前轮指令

    :param ctx: 能力构建上下文
    :return:
    """
    workspace_ref = ctx.forwarded_props.workspace_ref
    if ctx.user_id is None or workspace_ref is None:
        return CapabilityResult(capability=None)
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    if workspace_ref.kind == 'skill':
        return CapabilityResult(capability=None)

    if workspace_ref.kind == 'knowledge':
        try:
            knowledge = await ai_buddy_knowledge_service.get(db=ctx.db, pk=workspace_ref.id, user_id=ctx.user_id)
        except errors.NotFoundError:
            return CapabilityResult(capability=None)
        source = f'\n来源：{knowledge.source}' if knowledge.source else ''
        content = knowledge.content
        if len(content) > 4000:
            content = f'{content[:4000]}\n…完整内容请使用 get_knowledge({knowledge.id})'
        instruction = f'## 当前引用知识：{knowledge.title}{source}\n\n{content}'
    elif workspace_ref.kind == 'artifact':
        try:
            artifact = await ai_buddy_artifact_service.get(db=ctx.db, pk=workspace_ref.id, user_id=ctx.user_id)
        except errors.NotFoundError:
            return CapabilityResult(capability=None)
        content = artifact.content
        if len(content) > 4000:
            content = f'{content[:4000]}\n…完整内容请使用 get_artifact({artifact.id})'
        instruction = f'## 当前引用产物：{artifact.title}（{artifact.kind}）\n\n{content}'
    else:
        return CapabilityResult(capability=None)
    return CapabilityResult(
        capability=Capability(
            id=f'workspace-{workspace_ref.kind}-{workspace_ref.id}',
            description=f'当前引用的{workspace_ref.kind}',
            instructions=instruction,
        )
    )
