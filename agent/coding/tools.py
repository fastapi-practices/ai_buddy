from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.common.exception import errors
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.coding.attachments import import_input_attachment
from backend.plugin.ai_buddy.agent.coding.command_idempotency import run_idempotent_command
from backend.plugin.ai_buddy.agent.coding.delivery import deliver_sandbox_file
from backend.plugin.ai_buddy.agent.coding.test_report import run_tests_and_archive
from backend.plugin.ai_buddy.agent.coding.types import AgentRunContext, AgentToolSpec
from backend.plugin.ai_buddy.enums import AIBuddyArtifactKind, AIBuddyCommandReason, AIBuddyExecutionBackend
from backend.plugin.ai_buddy.schema.artifact import CreateAIBuddyArtifactParam, UpdateAIBuddyArtifactParam
from backend.plugin.ai_buddy.schema.command import AIBuddyBackgroundTaskDetail
from backend.plugin.ai_buddy.service.artifact_service import ai_buddy_artifact_service
from backend.plugin.ai_buddy.service.knowledge_service import ai_buddy_knowledge_service
from backend.plugin.ai_buddy.service.skill_service import ai_buddy_skill_service
from backend.plugin.ai_buddy.utils.skill_parser import skill_file_guidance

_SNIPPET_CHARS = 240
_CONTENT_CHARS = 12000
ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(slots=True)
class BoundAgentTool:
    """已绑定的 Agent 工具"""

    spec: AgentToolSpec
    handler: ToolHandler


def _truncate(text: str, limit: int = _CONTENT_CHARS) -> str:
    """限制工具文本长度并标记截断

    :param text: 文本内容
    :param limit: 数量上限
    :return:
    """
    if len(text) <= limit:
        return text
    return f'{text[:limit]}\n…内容已截断'


def _string(arguments: dict[str, Any], key: str, *, required: bool = True) -> str:
    """提取并校验工具字符串参数

    :param arguments: 工具参数
    :param key: 参数键
    :param required: 是否必填
    :return:
    """
    value = arguments.get(key)
    if value is None:
        if required:
            raise errors.RequestError(msg=f'缺少参数 {key}')
        return ''
    return str(value)


def _format_background_task(task: AIBuddyBackgroundTaskDetail) -> str:
    """渲染后台命令状态与新增输出

    :param task: 后台命令任务状态
    :return:
    """
    state = '运行中' if task.running else f'已结束，退出码 {task.exit_code if task.exit_code is not None else -1}'
    error = f'\n错误：{task.error}' if task.error else ''
    return f'状态：{state}{error}\n下次游标：{task.cursor}\n{task.logs}'.rstrip()


async def _bash_background(ctx: AgentRunContext, arguments: dict[str, Any]) -> str:
    """启动工作区后台命令并返回任务 ID

    :param ctx: 运行上下文
    :param arguments: 工具参数
    :return:
    """
    task_id = await ctx.sandbox.run_background(command=_string(arguments, 'command'))
    return f'后台命令已启动，任务 ID：{task_id}'


async def _bash_task_output(ctx: AgentRunContext, arguments: dict[str, Any]) -> str:
    """查询后台命令状态并读取新增输出

    :param ctx: 运行上下文
    :param arguments: 工具参数
    :return:
    """
    task = await ctx.sandbox.get_background_task(task_id=_string(arguments, 'task_id'), cursor=arguments.get('cursor'))
    return _format_background_task(task)


async def _bash_task_stop(ctx: AgentRunContext, arguments: dict[str, Any]) -> str:
    """中断工作区后台命令

    :param ctx: 运行上下文
    :param arguments: 工具参数
    :return:
    """
    await ctx.sandbox.stop_background(task_id=_string(arguments, 'task_id'))
    return '已请求中断后台命令'


async def _search_knowledge(ctx: AgentRunContext, arguments: dict[str, Any]) -> str:
    """按用户权限检索知识内容

    :param ctx: 运行上下文
    :param arguments: 工具参数
    :return:
    """
    query = _string(arguments, 'query')
    async with async_db_session() as db:
        hits = await ai_buddy_knowledge_service.search(db=db, query=query, user_id=ctx.user_id)
    if not hits:
        return '未找到匹配知识'
    snippets: list[str] = []
    for item in hits:
        normalized = ' '.join(item.content.split())
        snippet = normalized if len(normalized) <= _SNIPPET_CHARS else f'{normalized[:_SNIPPET_CHARS]}…'
        snippets.append(f'- #{item.knowledge_id} {item.title}（{item.score:.2f}）\n  {snippet}')
    return '匹配知识片段：\n' + '\n'.join(snippets)


async def _get_knowledge(ctx: AgentRunContext, arguments: dict[str, Any]) -> str:
    """读取用户可访问的知识详情

    :param ctx: 运行上下文
    :param arguments: 工具参数
    :return:
    """
    knowledge_id = int(arguments.get('knowledge_id') or 0)
    try:
        async with async_db_session() as db:
            knowledge = await ai_buddy_knowledge_service.get(db=db, pk=knowledge_id, user_id=ctx.user_id)
    except errors.NotFoundError:
        return '知识不存在'
    source = f'\n来源：{knowledge.source}' if knowledge.source else ''
    return f'## 知识：{knowledge.title}{source}\n\n{_truncate(knowledge.content)}'


async def _list_skills(ctx: AgentRunContext, _arguments: dict[str, Any]) -> str:
    """列出用户可访问的技能

    :param ctx: 运行上下文
    :return:
    """
    async with async_db_session() as db:
        skills = await ai_buddy_skill_service.get_all(db=db, user_id=ctx.user_id, include_content=False)
    if not skills:
        return '没有可用技能'
    lines = [f'- #{item.id} {item.name} v{item.version}：{item.description or "无描述"}' for item in skills]
    return '可用技能：\n' + '\n'.join(lines)


async def _get_skill(ctx: AgentRunContext, arguments: dict[str, Any]) -> str:
    """读取用户可访问的技能内容

    :param ctx: 运行上下文
    :param arguments: 工具参数
    :return:
    """
    skill_id = int(arguments.get('skill_id') or 0)
    try:
        async with async_db_session() as db:
            skill = await ai_buddy_skill_service.get(db=db, pk=skill_id, user_id=ctx.user_id)
    except errors.NotFoundError:
        return '技能不存在'
    return f'## 技能：{skill.name} v{skill.version}\n{skill_file_guidance(skill.id)}\n\n{_truncate(skill.content)}'


async def _read_skill_file(ctx: AgentRunContext, arguments: dict[str, Any]) -> str:
    """读取当前用户可访问的技能包文件

    :param ctx: 运行上下文
    :param arguments: 工具参数
    :return:
    """
    try:
        async with async_db_session() as db:
            return await ai_buddy_skill_service.read_file(
                db=db,
                pk=int(arguments.get('skill_id') or 0),
                user_id=ctx.user_id,
                path=_string(arguments, 'path'),
                offset=int(arguments.get('offset', 0)),
                limit=int(arguments.get('limit', 12000)),
            )
    except (errors.NotFoundError, errors.RequestError) as exc:
        return exc.msg


def _skill_file_tool(ctx: AgentRunContext) -> BoundAgentTool:
    """为编码宿主绑定技能文件只读工具

    :param ctx: 运行上下文
    :return:
    """
    return BoundAgentTool(
        spec=AgentToolSpec(
            name='read_skill_file',
            description='读取技能包内相对路径的 UTF-8 文本，按字符分页；脚本只读不执行',
            parameters={
                'type': 'object',
                'properties': {
                    'skill_id': {'type': 'integer', 'description': '技能 ID'},
                    'path': {'type': 'string', 'description': '相对技能包根目录的文件路径'},
                    'offset': {'type': 'integer', 'minimum': 0, 'default': 0, 'description': '起始字符，从 0 计'},
                    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 12000, 'default': 12000},
                },
                'required': ['skill_id', 'path'],
            },
        ),
        handler=lambda arguments: _read_skill_file(ctx, arguments),
    )


async def _list_artifacts(ctx: AgentRunContext, _arguments: dict[str, Any]) -> str:
    """列出当前对话的产物

    :param ctx: 运行上下文
    :return:
    """
    async with async_db_session() as db:
        rows = await ai_buddy_artifact_service.get_all(db=db, user_id=ctx.user_id)
    if not rows:
        return '没有已保存产物'
    return '已保存产物：\n' + '\n'.join(f'- #{item.id} {item.title}（{item.kind}）' for item in rows)


async def _get_artifact(ctx: AgentRunContext, arguments: dict[str, Any]) -> str:
    """读取用户可访问的产物内容

    :param ctx: 运行上下文
    :param arguments: 工具参数
    :return:
    """
    artifact_id = int(arguments.get('artifact_id') or 0)
    try:
        async with async_db_session() as db:
            artifact = await ai_buddy_artifact_service.get(db=db, pk=artifact_id, user_id=ctx.user_id)
    except errors.NotFoundError:
        return '产物不存在'
    return f'## 产物：{artifact.title}（{artifact.kind}）\n\n{_truncate(artifact.content)}'


async def _write_artifact(ctx: AgentRunContext, arguments: dict[str, Any]) -> str:
    """校验并保存当前对话的产物

    :param ctx: 运行上下文
    :param arguments: 工具参数
    :return:
    """
    title = _string(arguments, 'title').strip()
    kind = AIBuddyArtifactKind(arguments.get('kind', AIBuddyArtifactKind.text))
    content = _string(arguments, 'content')
    artifact_id = arguments.get('artifact_id')
    async with async_db_session.begin() as db:
        if artifact_id:
            await ai_buddy_artifact_service.update(
                db=db,
                pk=int(artifact_id),
                user_id=ctx.user_id,
                obj=UpdateAIBuddyArtifactParam(title=title or None, kind=kind, content=content),
            )
            return f'已更新产物 #{int(artifact_id)}'
        created = await ai_buddy_artifact_service.create(
            db=db,
            user_id=ctx.user_id,
            obj=CreateAIBuddyArtifactParam(title=title, kind=kind, content=content),
        )
        return f'已保存产物 #{created.id} {created.title}'


def _delivery_tools(ctx: AgentRunContext) -> list[BoundAgentTool]:
    """为服务端沙箱绑定文件交付工具，本机执行的文件已在用户电脑上，不提供

    :param ctx: 运行上下文
    :return:
    """
    if ctx.sandbox is None or ctx.sandbox.execution_backend != AIBuddyExecutionBackend.sandbox:
        return []

    async def deliver_file(arguments: dict[str, Any]) -> str:
        """把沙箱工作区文件交付为持久产物

        :param arguments: 工具参数
        :return:
        """
        kind = _string(arguments, 'kind', required=False)
        return await deliver_sandbox_file(
            ctx=ctx,
            path=_string(arguments, 'path'),
            title=_string(arguments, 'title', required=False).strip() or None,
            kind=AIBuddyArtifactKind(kind) if kind else None,
        )

    return [
        BoundAgentTool(
            spec=AgentToolSpec(
                name='deliver_file',
                description=(
                    '把沙箱工作区内要交给用户的最终文件保存为持久产物并返回产物 ID；'
                    '沙箱磁盘可能被回收，依赖、日志和中间文件不要交付'
                ),
                parameters={
                    'type': 'object',
                    'properties': {
                        'path': {
                            'type': 'string',
                            'minLength': 1,
                            'description': '工作区内的文件路径，建议放在 outbound/ 目录',
                        },
                        'title': {'type': 'string', 'description': '产物标题，默认使用文件名'},
                        'kind': {
                            'type': 'string',
                            'enum': AIBuddyArtifactKind.get_member_values(),
                            'description': (
                                '产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他，'
                                '默认按文件类型推断'
                            ),
                        },
                    },
                    'required': ['path'],
                    'additionalProperties': False,
                },
                mutating=True,
            ),
            handler=deliver_file,
        )
    ]


def build_builtin_tools(ctx: AgentRunContext) -> list[BoundAgentTool]:
    """
    构建 Agent 内置工具和资源引用工具

    :param ctx: 运行上下文
    :return:
    """

    async def read_file(arguments: dict[str, Any]) -> str:
        """按行范围读取工作区文件

        :param arguments: 工具参数
        :return:
        """
        return await ctx.sandbox.read_file(
            path=_string(arguments, 'path'),
            offset=int(arguments.get('offset') or 0),
            limit=None if arguments.get('limit') is None else int(arguments['limit']),
        )

    async def write_file(arguments: dict[str, Any]) -> str:
        """在大小限制内写入工作区文件

        :param arguments: 工具参数
        :return:
        """
        return await ctx.sandbox.write_file(path=_string(arguments, 'path'), content=_string(arguments, 'content'))

    async def edit_file(arguments: dict[str, Any]) -> str:
        """替换工作区文件中的指定内容

        :param arguments: 工具参数
        :return:
        """
        return await ctx.sandbox.edit_file(
            path=_string(arguments, 'path'),
            old_text=_string(arguments, 'old_text'),
            new_text=_string(arguments, 'new_text'),
        )

    async def bash(arguments: dict[str, Any]) -> str:
        """执行编码工具的工作区命令

        :param arguments: 工具参数
        :return:
        """
        result = await run_idempotent_command(
            ctx=ctx,
            command=_string(arguments, 'command'),
            idempotency_key=_string(arguments, 'idempotency_key', required=False) or None,
        )
        output = f'{result.stdout}{result.stderr}'
        if result.reason != AIBuddyCommandReason.completed:
            output = f'{output}\n命令未正常完成：{result.reason}' + ('，输出已截断' if result.truncated else '')
        return f'exit {result.exit_code if result.exit_code is not None else -1}\n{output}'.rstrip()

    async def ls(arguments: dict[str, Any]) -> str:
        """列出编码工作区目录

        :param arguments: 工具参数
        :return:
        """
        path = _string(arguments, 'path', required=False) or '.'
        entries = await ctx.sandbox.list_entries(path=path)
        lines = []
        for item in entries:
            suffix = '/' if item['is_dir'] else f' {item["size"]}B'
            lines.append(f'{item["path"]}{suffix}')
        return '\n'.join(lines) or '目录为空'

    async def git_status(_arguments: dict[str, Any]) -> str:
        """读取工作区 Git 状态

        :param _arguments: 工具参数
        :return:
        """
        return _truncate(await ctx.sandbox.git_status())

    async def git_diff(arguments: dict[str, Any]) -> str:
        """按范围读取工作区未提交差异

        :param arguments: 工具参数
        :return:
        """
        return _truncate(await ctx.sandbox.git_diff(scope=arguments.get('scope', 'all')))

    tools = [
        BoundAgentTool(
            spec=AgentToolSpec(
                name='read',
                description='读取工作区文件，可指定起始行和行数',
                parameters={
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string', 'description': '相对工作区的文件路径'},
                        'offset': {'type': 'integer', 'description': '起始行，从 0 计'},
                        'limit': {'type': 'integer', 'description': '最多返回行数'},
                    },
                    'required': ['path'],
                },
            ),
            handler=read_file,
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='write',
                description='创建或覆盖工作区文件',
                parameters={
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string', 'description': '相对工作区的文件路径'},
                        'content': {'type': 'string', 'description': '文件内容'},
                    },
                    'required': ['path', 'content'],
                },
                mutating=True,
            ),
            handler=write_file,
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='edit',
                description='精确替换工作区文件中的一段文本，old_text 必须唯一',
                parameters={
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string', 'description': '相对工作区的文件路径'},
                        'old_text': {'type': 'string', 'description': '要替换的原文本'},
                        'new_text': {'type': 'string', 'description': '替换后的文本'},
                    },
                    'required': ['path', 'old_text', 'new_text'],
                },
                mutating=True,
            ),
            handler=edit_file,
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='bash',
                description='在工作区根目录执行 shell 命令',
                parameters={
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string', 'description': '要执行的命令'},
                        'idempotency_key': {
                            'type': 'string',
                            'pattern': '^[A-Za-z0-9_.:-]{8,128}$',
                            'description': '幂等键，重试同一命令时传相同的值以避免重复产生副作用',
                        },
                    },
                    'required': ['command'],
                },
                mutating=True,
            ),
            handler=bash,
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='bash_background',
                description='在工作区后台启动长时间命令，立即返回任务 ID，之后用 bash_task_output 查询',
                parameters={
                    'type': 'object',
                    'properties': {'command': {'type': 'string', 'description': '要在后台执行的命令'}},
                    'required': ['command'],
                },
                mutating=True,
            ),
            handler=lambda arguments: _bash_background(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='bash_task_output',
                description='查询后台命令的运行状态、退出码和自上次游标以来的新输出',
                parameters={
                    'type': 'object',
                    'properties': {
                        'task_id': {'type': 'string', 'description': '后台命令任务 ID'},
                        'cursor': {'type': 'integer', 'description': '上次返回的游标，首次读取不传'},
                    },
                    'required': ['task_id'],
                },
            ),
            handler=lambda arguments: _bash_task_output(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='bash_task_stop',
                description='中断仍在运行的后台命令',
                parameters={
                    'type': 'object',
                    'properties': {'task_id': {'type': 'string', 'description': '后台命令任务 ID'}},
                    'required': ['task_id'],
                },
                mutating=True,
            ),
            handler=lambda arguments: _bash_task_stop(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='ls',
                description='列出工作区目录',
                parameters={
                    'type': 'object',
                    'properties': {'path': {'type': 'string', 'description': '相对工作区的目录路径，默认根目录'}},
                },
            ),
            handler=ls,
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='git_status',
                description='只读检查工作区 Git 分支与文件状态，桌面端支持已授权绑定的 worktree',
                parameters={'type': 'object', 'properties': {}, 'additionalProperties': False},
            ),
            handler=git_status,
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='git_diff',
                description='只读查询工作区 Git 差异，默认分别输出已暂存和未暂存部分',
                parameters={
                    'type': 'object',
                    'properties': {
                        'scope': {
                            'type': 'string',
                            'enum': ['all', 'staged', 'unstaged'],
                            'default': 'all',
                            'description': 'all 为已暂存与未暂存，staged 为已暂存，unstaged 为未暂存',
                        }
                    },
                    'additionalProperties': False,
                },
            ),
            handler=git_diff,
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='search_knowledge',
                description='按语义检索企业知识库，返回最相关切片',
                parameters={
                    'type': 'object',
                    'properties': {'query': {'type': 'string', 'description': '检索文本'}},
                    'required': ['query'],
                },
            ),
            handler=lambda arguments: _search_knowledge(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='get_knowledge',
                description='读取一条知识的完整内容',
                parameters={
                    'type': 'object',
                    'properties': {'knowledge_id': {'type': 'integer', 'description': '知识 ID'}},
                    'required': ['knowledge_id'],
                },
            ),
            handler=lambda arguments: _get_knowledge(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='list_skills',
                description='列出企业技能名称和描述，需要细节时再 get_skill',
                parameters={'type': 'object', 'properties': {}},
            ),
            handler=lambda arguments: _list_skills(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='get_skill',
                description='读取一条技能的完整说明',
                parameters={
                    'type': 'object',
                    'properties': {'skill_id': {'type': 'integer', 'description': '技能 ID'}},
                    'required': ['skill_id'],
                },
            ),
            handler=lambda arguments: _get_skill(ctx, arguments),
        ),
        _skill_file_tool(ctx),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='list_artifacts',
                description='列出当前用户已保存的工作产物',
                parameters={'type': 'object', 'properties': {}},
            ),
            handler=lambda arguments: _list_artifacts(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='get_artifact',
                description='读取一条产物的完整内容',
                parameters={
                    'type': 'object',
                    'properties': {'artifact_id': {'type': 'integer', 'description': '产物 ID'}},
                    'required': ['artifact_id'],
                },
            ),
            handler=lambda arguments: _get_artifact(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='write_artifact',
                description='把完成的文档、代码或报告保存为产物；传入 artifact_id 则更新',
                parameters={
                    'type': 'object',
                    'properties': {
                        'title': {'type': 'string', 'description': '产物标题'},
                        'kind': {
                            'type': 'string',
                            'enum': AIBuddyArtifactKind.get_member_values(),
                            'default': AIBuddyArtifactKind.text.value,
                            'description': (
                                '产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他'
                            ),
                        },
                        'content': {'type': 'string', 'description': '产物内容'},
                        'artifact_id': {'type': 'integer', 'description': '已有产物 ID，更新时传入'},
                    },
                    'required': ['title', 'content'],
                },
                mutating=True,
            ),
            handler=lambda arguments: _write_artifact(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='run_tests',
                description='执行用户指定或已确认的测试命令并保存可下载的事实报告；不要猜测测试命令或用例通过数',
                parameters={
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string', 'minLength': 1, 'description': '明确的测试 shell 命令'}
                    },
                    'required': ['command'],
                    'additionalProperties': False,
                },
                mutating=True,
            ),
            handler=lambda arguments: run_tests_and_archive(ctx=ctx, command=arguments['command']),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='import_attachment',
                description='将本轮用户附件原始字节导入 inbound 目录，返回路径、大小和 SHA-256',
                parameters={
                    'type': 'object',
                    'properties': {'attachment_id': {'type': 'integer', 'minimum': 1}},
                    'required': ['attachment_id'],
                    'additionalProperties': False,
                },
                mutating=True,
            ),
            handler=lambda arguments: import_input_attachment(ctx, arguments['attachment_id']),
        ),
    ]
    return [*tools, *_delivery_tools(ctx)]


def build_buddy_resource_tools(ctx: AgentRunContext) -> list[BoundAgentTool]:
    """
    构建编码宿主可调用的 Buddy 知识、技能与产物工具

    :param ctx: 运行上下文
    :return:
    """
    return [
        BoundAgentTool(
            spec=AgentToolSpec(
                name='search_knowledge',
                description='按语义检索企业知识库，返回最相关切片',
                parameters={
                    'type': 'object',
                    'properties': {'query': {'type': 'string', 'description': '检索文本'}},
                    'required': ['query'],
                },
            ),
            handler=lambda arguments: _search_knowledge(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='get_knowledge',
                description='读取一条知识的完整内容',
                parameters={
                    'type': 'object',
                    'properties': {'knowledge_id': {'type': 'integer', 'description': '知识 ID'}},
                    'required': ['knowledge_id'],
                },
            ),
            handler=lambda arguments: _get_knowledge(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='list_skills',
                description='列出企业技能名称和描述，需要细节时再 get_skill',
                parameters={'type': 'object', 'properties': {}},
            ),
            handler=lambda arguments: _list_skills(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='get_skill',
                description='读取一条技能的完整说明',
                parameters={
                    'type': 'object',
                    'properties': {'skill_id': {'type': 'integer', 'description': '技能 ID'}},
                    'required': ['skill_id'],
                },
            ),
            handler=lambda arguments: _get_skill(ctx, arguments),
        ),
        _skill_file_tool(ctx),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='list_artifacts',
                description='列出当前用户已保存的工作产物',
                parameters={'type': 'object', 'properties': {}},
            ),
            handler=lambda arguments: _list_artifacts(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='get_artifact',
                description='读取一条产物的完整内容',
                parameters={
                    'type': 'object',
                    'properties': {'artifact_id': {'type': 'integer', 'description': '产物 ID'}},
                    'required': ['artifact_id'],
                },
            ),
            handler=lambda arguments: _get_artifact(ctx, arguments),
        ),
        BoundAgentTool(
            spec=AgentToolSpec(
                name='write_artifact',
                description='把完成的文档、代码或报告保存为产物；传入 artifact_id 则更新',
                parameters={
                    'type': 'object',
                    'properties': {
                        'title': {'type': 'string', 'description': '产物标题'},
                        'kind': {
                            'type': 'string',
                            'enum': AIBuddyArtifactKind.get_member_values(),
                            'default': AIBuddyArtifactKind.text.value,
                            'description': (
                                '产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他'
                            ),
                        },
                        'content': {'type': 'string', 'description': '产物内容'},
                        'artifact_id': {'type': 'integer', 'description': '已有产物 ID，更新时传入'},
                    },
                    'required': ['title', 'content'],
                },
                mutating=True,
            ),
            handler=lambda arguments: _write_artifact(ctx, arguments),
        ),
    ]
