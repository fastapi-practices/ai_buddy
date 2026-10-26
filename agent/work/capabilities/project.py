from pydantic_ai import InstructionPart
from pydantic_ai.capabilities import Capability

from backend.common.exception import errors
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.service.project_service import ai_buddy_project_service


async def build_project_capability(ctx: CapabilityContext) -> CapabilityResult:
    """工作与编码运行共同验证归属并识别当前项目

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.user_id is None:
        return CapabilityResult(capability=None)
    project_id = getattr(ctx.forwarded_props, 'project_id', None)
    if ctx.conversation_id:
        conversation = await ai_buddy_conversation_dao.get_by_conversation_id(ctx.db, ctx.conversation_id)
        if conversation is not None:
            if conversation.user_id != ctx.user_id:
                raise errors.NotFoundError(msg='对话不存在')
            project_id = conversation.project_id
    if project_id is None:
        return CapabilityResult(capability=None)
    project = await ai_buddy_project_service.get(db=ctx.db, pk=project_id, user_id=ctx.user_id)
    return CapabilityResult(
        capability=Capability(
            id='project-context',
            description='所属项目',
            instructions=InstructionPart(f'当前项目：{project.name}', on_change='append'),
        )
    )
