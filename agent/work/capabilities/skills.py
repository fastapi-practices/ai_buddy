from collections.abc import Awaitable, Callable, Sequence

from pydantic_ai import ModelRetry
from pydantic_ai.capabilities import Capability

from backend.common.exception import errors
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.model import AIBuddySkill
from backend.plugin.ai_buddy.service.skill_service import ai_buddy_skill_service
from backend.plugin.ai_buddy.utils.skill_parser import skill_file_guidance, skill_markdown_body


def build_skill_instruction(skill: AIBuddySkill) -> str:
    """
    构建技能指令

    :param skill: 技能记录
    :return:
    """
    description = skill.description.strip() if skill.description else ''
    body = skill_markdown_body(skill.content)
    version = skill.version.strip() if skill.version else ''
    title = f'## 技能：{skill.name}（{version}）' if version else f'## 技能：{skill.name}'
    guidance = skill_file_guidance(skill.id)
    if description:
        return f'{title}\n{description}\n{guidance}\n\n{body}'
    return f'{title}\n{guidance}\n\n{body}'


def _skill_loader(*, skill_id: int, user_id: int) -> Callable[[], Awaitable[str]]:
    """
    在模型加载技能时重新校验可见性并读取正文

    :param skill_id: 技能 ID
    :param user_id: 用户 ID
    :return:
    """

    async def load_instructions() -> str:
        """使用独立会话读取当前仍可访问的技能"""
        try:
            async with async_db_session() as db:
                skill = await ai_buddy_skill_service.get(db=db, pk=skill_id, user_id=user_id)
            return build_skill_instruction(skill)
        except (errors.NotFoundError, errors.RequestError) as exc:
            raise ModelRetry('技能当前不可用，请使用其他技能或继续完成任务') from exc

    return load_instructions


async def build_skills_capability(ctx: CapabilityContext) -> Sequence[CapabilityResult]:
    """
    将技能注入为可按需加载的能力

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.user_id is None:
        return ()
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return ()

    workspace_ref = ctx.forwarded_props.workspace_ref
    if workspace_ref is not None and workspace_ref.kind == 'skill':
        try:
            skill = await ai_buddy_skill_service.get(db=ctx.db, pk=workspace_ref.id, user_id=ctx.user_id)
        except errors.NotFoundError:
            return ()
        return (
            CapabilityResult(
                capability=Capability(
                    id=f'skill-{skill.id}',
                    description=skill.description or skill.name,
                    instructions=build_skill_instruction(skill),
                )
            ),
        )

    if not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        return ()

    skills = await ai_buddy_skill_service.get_all(db=ctx.db, user_id=ctx.user_id, include_content=False)
    return tuple(
        CapabilityResult(
            capability=Capability(
                id=f'skill-{skill.id}',
                description=skill.description or skill.name,
                instructions=_skill_loader(skill_id=skill.id, user_id=ctx.user_id),
                defer_loading=True,
            ),
            introduces_function_tool_source=True,
        )
        for skill in skills
    )
