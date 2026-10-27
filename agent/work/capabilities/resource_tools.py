from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError
from pydantic_ai import RunContext
from pydantic_ai.capabilities import Capability
from pydantic_ai.toolsets import FunctionToolset

from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.cron.schedule import next_run_time
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyAssistantCategory, AIBuddyChatGenerationType, AIBuddyOrigin
from backend.plugin.ai_buddy.model.assistant import AIBuddyAssistant
from backend.plugin.ai_buddy.model.cron import AIBuddyCron
from backend.plugin.ai_buddy.model.expert import AIBuddyExpert
from backend.plugin.ai_buddy.model.knowledge_base import AIBuddyKnowledgeBase
from backend.plugin.ai_buddy.model.mcp import AIBuddyMcp
from backend.plugin.ai_buddy.model.skill import AIBuddySkill
from backend.plugin.ai_buddy.schema.assistant import CreateAIBuddyAssistantParam, UpdateAIBuddyAssistantParam
from backend.plugin.ai_buddy.schema.cron import CreateAIBuddyCronParam
from backend.plugin.ai_buddy.schema.expert import CreateAIBuddyExpertParam, UpdateAIBuddyExpertParam
from backend.plugin.ai_buddy.service.assistant_service import ai_buddy_assistant_service
from backend.plugin.ai_buddy.service.cron_service import ai_buddy_cron_service
from backend.plugin.ai_buddy.service.expert_service import ai_buddy_expert_service
from backend.plugin.ai_buddy.service.knowledge_base_service import ai_buddy_knowledge_base_service
from backend.plugin.ai_buddy.service.mcp_service import ai_buddy_mcp_service
from backend.plugin.ai_buddy.service.skill_service import ai_buddy_skill_service
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID
from backend.plugin.ai_buddy.utils.skill_parser import build_skill_markdown
from backend.utils.timezone import timezone

if TYPE_CHECKING:
    from collections.abc import Sequence

_LIST_LIMIT = 30
_DESCRIPTION_PREVIEW_CHARS = 60

type ResourceKind = Literal['cron', 'assistant', 'expert', 'skill', 'mcp', 'knowledge_base']
type ResourceRow = AIBuddyAssistant | AIBuddyExpert | AIBuddySkill | AIBuddyMcp | AIBuddyKnowledgeBase


def build_resource_tools_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    构建定时任务、助手、专家和技能的管理工具，延迟到模型加载时才暴露工具定义

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.user_id is None:
        return CapabilityResult(capability=None)
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    # IM 尚无审批回调，定时任务触发的轮次无人值守，这两类来源不开放持久资源的写入
    if ctx.origin != AIBuddyOrigin.web:
        return CapabilityResult(capability=None)
    if not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        return CapabilityResult(capability=None)

    toolset: FunctionToolset[ChatAgentDeps] = FunctionToolset[ChatAgentDeps]()
    toolset.tool(list_resources)
    toolset.tool(create_cron)
    toolset.tool(set_cron_enabled)
    toolset.tool(delete_cron)
    toolset.tool(create_assistant)
    toolset.tool(update_assistant)
    toolset.tool(create_expert)
    toolset.tool(update_expert)
    toolset.tool(create_skill)
    toolset.tool(update_skill)
    return CapabilityResult(
        capability=Capability(
            id='resource-tools',
            description='查看、创建、修改定时任务、助手、专家和技能，仅在用户明确提出时加载',
            toolsets=[toolset],
            defer_loading=True,
        ),
        introduces_function_tool_source=True,
    )


async def list_resources(ctx: RunContext[ChatAgentDeps], kind: ResourceKind) -> str:
    """
    列出当前用户可用的资源和 ID，创建前先查看以避免重复，修改、删除或绑定前用它取得 ID

    :param ctx: 运行上下文
    :param kind: 资源类型：cron 定时任务、assistant 助手、expert 专家、skill 技能、mcp MCP 服务、knowledge_base 知识库
    :return:
    """
    user_id = ctx.deps.user_id
    rows: Sequence[AIBuddyCron | ResourceRow]
    async with async_db_session() as db:
        if kind == 'cron':
            rows = await ai_buddy_cron_service.get_all(db=db, user_id=user_id)
        elif kind == 'assistant':
            rows = await ai_buddy_assistant_service.get_all(db=db, user_id=user_id)
        elif kind == 'expert':
            rows = await ai_buddy_expert_service.get_all(db=db, user_id=user_id)
        elif kind == 'skill':
            rows = await ai_buddy_skill_service.get_all(db=db, user_id=user_id, include_content=False)
        elif kind == 'mcp':
            rows = await ai_buddy_mcp_service.get_all(db=db, user_id=user_id)
        else:
            rows = await ai_buddy_knowledge_base_service.get_all(db=db, user_id=user_id)
    if not rows:
        return f'没有可用的{kind}'
    lines = [
        _describe_cron(row) if isinstance(row, AIBuddyCron) else _describe_resource(row) for row in rows[:_LIST_LIMIT]
    ]
    suffix = f'\n仅显示前 {_LIST_LIMIT} 个' if len(rows) > _LIST_LIMIT else ''
    header = f'定时任务（时区 {settings.DATETIME_TIMEZONE}）：' if kind == 'cron' else f'{kind}：'
    return header + '\n' + '\n'.join(lines) + suffix


async def create_cron(
    ctx: RunContext[ChatAgentDeps],
    name: str,
    trigger: str,
    prompt: str,
    *,
    fresh_thread: bool = False,
) -> str:
    """
    为当前对话创建定时任务，到点后 prompt 会作为用户消息发送到当前对话

    :param ctx: 运行上下文
    :param name: 任务名称，简短，动词开头，不含日期和时间，最多 80 个字符
    :param trigger: 调度表达式，cron:分 时 日 月 周、interval:秒数（不小于 60）或 date:ISO 时间（晚于当前）
    :param prompt: 到点执行的提示词，写成用户发给 AI 的消息且不含调度信息，需自包含，最多 2000 个字符
    :param fresh_thread: 每次执行是否新开对话
    :return:
    """
    if not ctx.deps.conversation_id:
        return '当前没有可绑定的对话'
    try:
        obj = CreateAIBuddyCronParam(
            name=name,
            conversation_id=ctx.deps.conversation_id,
            trigger=trigger,
            prompt=prompt,
            fresh_thread=fresh_thread,
        )
        async with async_db_session.begin() as db:
            cron = await ai_buddy_cron_service.create(db=db, obj=obj, user_id=ctx.deps.user_id)
            summary = _describe_cron(cron)
    except (ValidationError, errors.BaseExceptionError) as exc:
        return _failure_message(exc, '创建')
    return f'已创建定时任务：\n{summary}'


async def set_cron_enabled(ctx: RunContext[ChatAgentDeps], cron_id: int, *, enabled: bool) -> str:
    """
    暂停或恢复一个定时任务，任务 ID 来自 list_resources

    :param ctx: 运行上下文
    :param cron_id: 任务 ID
    :param enabled: true 恢复，false 暂停
    :return:
    """
    try:
        async with async_db_session.begin() as db:
            cron = await ai_buddy_cron_service.set_enabled(db=db, pk=cron_id, user_id=ctx.deps.user_id, enabled=enabled)
            upcoming = next_run_time(cron.trigger, last_run_time=cron.last_run_time, created_time=cron.created_time)
            label = f'#{cron.id} {cron.name}'
    except errors.BaseExceptionError as exc:
        return _failure_message(exc, '恢复' if enabled else '暂停')
    if not enabled:
        return f'已暂停定时任务 {label}'
    return f'已恢复定时任务 {label}，下次执行 {_format_when(upcoming)}'


async def delete_cron(ctx: RunContext[ChatAgentDeps], cron_id: int) -> str:
    """
    删除当前用户的一个定时任务，任务 ID 来自 list_resources

    :param ctx: 运行上下文
    :param cron_id: 任务 ID
    :return:
    """
    try:
        async with async_db_session.begin() as db:
            await ai_buddy_cron_service.delete(db=db, pk=cron_id, user_id=ctx.deps.user_id)
    except errors.BaseExceptionError as exc:
        return _failure_message(exc, '删除')
    return f'已删除定时任务 #{cron_id}'


async def create_assistant(
    ctx: RunContext[ChatAgentDeps],
    name: str,
    prompt: str,
    description: str | None = None,
    category: AIBuddyAssistantCategory | None = None,
    starters: list[str] | None = None,
) -> str:
    """
    创建个人助手

    :param ctx: 运行上下文
    :param name: 助手名称，最多 64 个字符
    :param prompt: 角色提示词
    :param description: 一句话说明，最多 512 个字符
    :param category: 分类编码，按助手主要用途选择
    :param starters: 开场白，最多 8 条，每条最多 256 个字符
    :return:
    """
    try:
        obj = CreateAIBuddyAssistantParam(
            name=name,
            prompt=prompt,
            description=description,
            category=category,
            starters=starters or [],
        )
        async with async_db_session.begin() as db:
            await ai_buddy_assistant_service.create(db=db, obj=obj, user_id=ctx.deps.user_id)
    except (ValidationError, errors.BaseExceptionError) as exc:
        return _failure_message(exc, '创建')
    return f'已创建助手：{name.strip()}'


async def update_assistant(
    ctx: RunContext[ChatAgentDeps],
    assistant_id: int,
    name: str | None = None,
    prompt: str | None = None,
    description: str | None = None,
    category: AIBuddyAssistantCategory | None = None,
    starters: list[str] | None = None,
) -> str:
    """
    修改个人助手，只传需要修改的字段，未传的保持不变；助手 ID 来自 list_resources，内置助手不能修改

    :param ctx: 运行上下文
    :param assistant_id: 助手 ID
    :param name: 新名称
    :param prompt: 新角色提示词，需给出完整内容而不是增量
    :param description: 新说明，传空字符串表示清空
    :param category: 新分类编码
    :param starters: 新开场白，整体替换
    :return:
    """
    try:
        async with async_db_session.begin() as db:
            current = await ai_buddy_assistant_service.get(db=db, pk=assistant_id, user_id=ctx.deps.user_id)
            obj = UpdateAIBuddyAssistantParam(
                name=_pick(name, current.name),
                prompt=_pick(prompt, current.prompt),
                description=_pick(description, current.description),
                category=_pick(category, current.category),
                starters=_pick(starters, list(current.starters or [])),
                sort=current.sort,
            )
            await ai_buddy_assistant_service.update(
                db=db, pk=assistant_id, obj=obj, user_id=ctx.deps.user_id, is_superuser=False
            )
    except (ValidationError, errors.BaseExceptionError) as exc:
        return _failure_message(exc, '修改')
    return f'已修改助手 #{assistant_id}'


async def create_expert(
    ctx: RunContext[ChatAgentDeps],
    name: str,
    prompt: str,
    description: str | None = None,
    starters: list[str] | None = None,
    mcp_ids: list[int] | None = None,
    skill_ids: list[int] | None = None,
    knowledge_ids: list[int] | None = None,
) -> str:
    """
    创建个人专家模板，可同时绑定默认的 MCP、技能和知识库

    :param ctx: 运行上下文
    :param name: 专家名称，最多 64 个字符
    :param prompt: 角色提示词
    :param description: 一句话说明，最多 512 个字符
    :param starters: 开场白，最多 8 条，每条最多 256 个字符
    :param mcp_ids: 默认 MCP ID，来自 list_resources(kind="mcp")，只绑定用户明确要求的
    :param skill_ids: 默认技能 ID，来自 list_resources(kind="skill")，只绑定用户明确要求的
    :param knowledge_ids: 默认知识库 ID，来自 list_resources(kind="knowledge_base")，只绑定用户明确要求的
    :return:
    """
    try:
        obj = CreateAIBuddyExpertParam(
            name=name,
            prompt=prompt,
            description=description,
            starters=starters or [],
            mcp_ids=mcp_ids or [],
            skill_ids=skill_ids or [],
            knowledge_ids=knowledge_ids or [],
        )
        async with async_db_session.begin() as db:
            await ai_buddy_expert_service.create(db=db, obj=obj, user_id=ctx.deps.user_id)
    except (ValidationError, errors.BaseExceptionError) as exc:
        return _failure_message(exc, '创建')
    return f'已创建专家：{name.strip()}'


async def update_expert(
    ctx: RunContext[ChatAgentDeps],
    expert_id: int,
    name: str | None = None,
    prompt: str | None = None,
    description: str | None = None,
    starters: list[str] | None = None,
    mcp_ids: list[int] | None = None,
    skill_ids: list[int] | None = None,
    knowledge_ids: list[int] | None = None,
) -> str:
    """
    修改个人专家模板，只传需要修改的字段，未传的保持不变；专家 ID 来自 list_resources，内置专家不能修改

    :param ctx: 运行上下文
    :param expert_id: 专家 ID
    :param name: 新名称
    :param prompt: 新角色提示词，需给出完整内容而不是增量
    :param description: 新说明，传空字符串表示清空
    :param starters: 新开场白，整体替换
    :param mcp_ids: 新的默认 MCP ID 列表，整体替换，传空列表表示清空
    :param skill_ids: 新的默认技能 ID 列表，整体替换，传空列表表示清空
    :param knowledge_ids: 新的默认知识库 ID 列表，整体替换，传空列表表示清空
    :return:
    """
    try:
        async with async_db_session.begin() as db:
            current = await ai_buddy_expert_service.get(db=db, pk=expert_id, user_id=ctx.deps.user_id)
            obj = UpdateAIBuddyExpertParam(
                name=_pick(name, current.name),
                prompt=_pick(prompt, current.prompt),
                description=_pick(description, current.description),
                starters=_pick(starters, list(current.starters or [])),
                mcp_ids=_pick(mcp_ids, list(current.mcp_ids or [])),
                skill_ids=_pick(skill_ids, list(current.skill_ids or [])),
                knowledge_ids=_pick(knowledge_ids, list(current.knowledge_ids or [])),
                sort=current.sort,
            )
            await ai_buddy_expert_service.update(
                db=db, pk=expert_id, obj=obj, user_id=ctx.deps.user_id, is_superuser=False
            )
    except (ValidationError, errors.BaseExceptionError) as exc:
        return _failure_message(exc, '修改')
    return f'已修改专家 #{expert_id}'


async def create_skill(
    ctx: RunContext[ChatAgentDeps],
    name: str,
    description: str,
    body: str,
    version: str = '0.1.0',
) -> str:
    """
    创建个人技能，只生成 SKILL.md，不含脚本和其他文件

    :param ctx: 运行上下文
    :param name: 技能名称，最多 64 个小写字母、数字和单个连字符
    :param description: 第三人称陈述技能做什么和何时使用，最多 1024 个字符
    :param body: SKILL.md 正文，不含 frontmatter
    :param version: 技能版本，最多 32 个字符
    :return:
    """
    try:
        content = build_skill_markdown(name=name, description=description, body=body, version=version)
        async with async_db_session.begin() as db:
            await ai_buddy_skill_service.create_from_payloads(
                db=db,
                user_id=ctx.deps.user_id,
                payloads=[(f'{name}/SKILL.md', content.encode())],
            )
    except errors.BaseExceptionError as exc:
        return _failure_message(exc, '创建')
    return f'已创建技能：{name}，下一轮对话起可用'


async def update_skill(
    ctx: RunContext[ChatAgentDeps],
    skill_id: int,
    description: str | None = None,
    body: str | None = None,
    version: str | None = None,
) -> str:
    """
    修改个人技能的说明、正文或版本，只传需要修改的字段；技能名称不能修改，内置技能不能修改

    :param ctx: 运行上下文
    :param skill_id: 技能 ID，来自 list_resources
    :param description: 新说明
    :param body: 新正文，需给出完整内容而不是增量
    :param version: 新版本，改动内容时建议同时升版本
    :return:
    """
    if description is None and body is None and version is None:
        return '修改失败：没有需要修改的内容'
    try:
        async with async_db_session.begin() as db:
            await ai_buddy_skill_service.update_content(
                db=db,
                pk=skill_id,
                user_id=ctx.deps.user_id,
                description=description,
                body=body,
                version=version,
            )
    except errors.BaseExceptionError as exc:
        return _failure_message(exc, '修改')
    return f'已修改技能 #{skill_id}，下一轮对话起生效'


def _failure_message(exc: ValidationError | errors.BaseExceptionError, action: str) -> str:
    """
    将失败原因整理为模型可据此修正参数的说明

    :param exc: 参数校验或业务异常
    :param action: 失败的操作
    :return:
    """
    if isinstance(exc, ValidationError):
        detail = '；'.join(f'{".".join(str(part) for part in item["loc"])}：{item["msg"]}' for item in exc.errors())
    else:
        detail = exc.msg
    return f'{action}失败：{detail}'


def _pick[T](value: T | None, current: T) -> T:
    """
    局部更新时，未传入的字段沿用现有值

    :param value: 传入的新值
    :param current: 现有值
    :return:
    """
    return current if value is None else value


def _format_when(upcoming: datetime | None) -> str:
    """
    格式化下次执行时间并附上时区

    :param upcoming: 下次执行时间
    :return:
    """
    return f'{timezone.to_str(upcoming)}（{settings.DATETIME_TIMEZONE}）' if upcoming else '无'


def _describe_cron(cron: AIBuddyCron) -> str:
    """
    生成定时任务的一行摘要

    :param cron: 定时任务
    :return:
    """
    if cron.status != StatusType.enable:
        state = '已停用'
    else:
        upcoming = next_run_time(cron.trigger, last_run_time=cron.last_run_time, created_time=cron.created_time)
        state = f'下次执行 {_format_when(upcoming)}' if upcoming else '已执行完毕'
    return f'- #{cron.id} {cron.name} | {cron.trigger} | {state}'


def _describe_resource(row: ResourceRow) -> str:
    """
    生成资源的一行摘要，内置资源会标明

    :param row: 资源记录
    :return:
    """
    owner = '（内置）' if row.user_id == SYSTEM_OWNER_USER_ID else ''
    description = ' '.join((row.description or '').split())
    if len(description) > _DESCRIPTION_PREVIEW_CHARS:
        description = f'{description[:_DESCRIPTION_PREVIEW_CHARS]}…'
    return f'- #{row.id} {row.name}{owner}' + (f'：{description}' if description else '')
