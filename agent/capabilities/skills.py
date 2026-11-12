from collections.abc import Awaitable, Callable, Sequence

from pydantic_ai import ModelRetry
from pydantic_ai.capabilities import Capability

from backend.common.exception import errors
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.agent.capabilities.sandbox_tools import sandbox_tools_enabled
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.model import AIBuddySkill
from backend.plugin.ai_buddy.security.artifact_scanner import scan_artifact
from backend.plugin.ai_buddy.service.skill_service import ai_buddy_skill_service
from backend.plugin.ai_buddy.utils.skill_parser import skill_file_guidance, skill_markdown_body


def build_skill_instruction(skill: AIBuddySkill, *, executable: bool = False) -> str:
    """
    构建技能指令

    :param skill: 技能记录
    :param executable: 本轮是否有沙箱可以执行技能脚本
    :return:
    """
    description = skill.description.strip() if skill.description else ''
    body = skill_markdown_body(skill.content)
    version = skill.version.strip() if skill.version else ''
    title = f'## 技能：{skill.name}（{version}）' if version else f'## 技能：{skill.name}'
    guidance = skill_file_guidance(skill.id, executable=executable)
    if description:
        return f'{title}\n{description}\n{guidance}\n\n{body}'
    return f'{title}\n{guidance}\n\n{body}'


def scan_skill(skill: AIBuddySkill) -> str | None:
    """
    扫描技能正文，命中提示注入或凭据外泄特征时返回风险摘要

    :param skill: 技能记录
    :return:
    """
    content = getattr(skill, 'content', '') or ''
    result = scan_artifact(content, source=f'skill:{skill.id}')
    return result.summary() if result.flagged else None


def _skill_loader(*, skill_id: int, user_id: int, executable: bool) -> Callable[[], Awaitable[str]]:
    """
    在模型加载技能时重新校验可见性并读取正文

    :param skill_id: 技能 ID
    :param user_id: 用户 ID
    :param executable: 本轮是否有沙箱可以执行技能脚本
    :return:
    """

    async def load_instructions() -> str:
        """使用独立会话读取当前仍可访问的技能"""
        try:
            async with async_db_session() as db:
                skill = await ai_buddy_skill_service.get(db=db, pk=skill_id, user_id=user_id)
        except (errors.NotFoundError, errors.RequestError) as exc:
            raise ModelRetry('技能当前不可用，请使用其他技能或继续完成任务') from exc
        threats = scan_skill(skill)
        if threats:
            raise ModelRetry(f'技能内容包含风险特征（{threats}），已拒绝加载，请改用其他技能')
        return build_skill_instruction(skill, executable=executable)

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

    executable = sandbox_tools_enabled(ctx)
    workspace_ref = ctx.forwarded_props.workspace_ref
    if workspace_ref is not None and workspace_ref.kind == 'skill':
        try:
            skill = await ai_buddy_skill_service.get(db=ctx.db, pk=workspace_ref.id, user_id=ctx.user_id)
        except errors.NotFoundError:
            return ()
        threats = scan_skill(skill)
        if threats:
            return (
                CapabilityResult(
                    capability=Capability(
                        id=f'skill-{skill.id}',
                        description=skill.description or skill.name,
                        instructions=(
                            f'技能「{skill.name}」的内容包含风险特征（{threats}），已扣留正文，请提示用户人工复核后再使用'
                        ),
                    )
                ),
            )
        return (
            CapabilityResult(
                capability=Capability(
                    id=f'skill-{skill.id}',
                    description=skill.description or skill.name,
                    instructions=build_skill_instruction(skill, executable=executable),
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
                instructions=_skill_loader(skill_id=skill.id, user_id=ctx.user_id, executable=executable),
                defer_loading=True,
            ),
            introduces_function_tool_source=True,
        )
        for skill in skills
    )
