from backend.plugin.ai_buddy.agent.coding.types import AgentRunContext
from backend.plugin.ai_buddy.enums import AIBuddyPermissionMode

_PERMISSION_HINT = {
    AIBuddyPermissionMode.ask: '写文件、编辑、执行命令和写入产物需要用户批准',
    AIBuddyPermissionMode.auto: '工作区内的读、写、编辑和命令会自动批准，不要越出工作区',
    AIBuddyPermissionMode.full: '工作区内工具全部可用；仍然不要尝试逃出工作区',
}


def build_agent_system_prompt(ctx: AgentRunContext) -> str:
    """
    构建 Agent 系统提示词

    :param ctx: 运行上下文
    :return:
    """
    lines = [
        '你是 Agent，在隔离编码目录中完成用户任务',
        '只用提供的工具。核心工具是 read、write、edit、bash、ls',
        '若提供 run_tests，用它执行已确认的测试命令并归档事实报告，不猜测测试命令；'
        '仅 completed 且退出码为 0 表示命令成功，不据此推断所有测试用例通过；归档失败必须说明',
        '当前是编码模式，以代码仓库、项目文件和开发环境为任务对象，交付项目变更及验证结果',
        '先理解相关代码和项目约定，再按用户要求修改；解释、评审或规划请求只输出结论，不主动修改文件',
        '项目、知识、技能和 MCP 是工作区引用，不要把它们复制进工作区，除非用户明确要求',
        '优先读取相关技能再动手。修改后运行与变更相关的检查，说明实际执行的检查、结果和无法验证的限制',
        '完成后给出简短结果，不要编造未执行的操作；权限与执行位置不改变用户任务的范围',
        f'当前权限模式：{ctx.permission_mode}。{_PERMISSION_HINT[ctx.permission_mode]}',
    ]
    if ctx.acp_runner_enabled:
        lines[:2] = [
            '通过 acp_runner 将编码任务委托给用户本机已安装的 Agent，文件和命令由本地 Agent 执行',
            f'本轮本地 Agent：{ctx.acp_runner_name}；本地工作目录：{ctx.acp_cwd}',
        ]
        lines.append('委托时传达任务范围和验证要求；外部 Agent 不自动继承 Buddy 的知识、技能或 MCP 配置')
    elif getattr(ctx.sandbox, 'execution_backend', None) == 'local':
        lines[0] = '你是 Agent，在用户桌面本机的操作系统沙箱中完成任务，文件写入限定在所选工作目录'
        lines.append(f'本轮执行后端：local；桌面工作目录：{ctx.sandbox.cwd}')
    if ctx.project_name:
        lines.append(f'当前项目：{ctx.project_name}')
    if ctx.goal:
        lines.append(f'对话目标：{ctx.goal}')
    reference_tools = {
        'knowledge': ('知识', 'get_knowledge'),
        'skill': ('技能', 'get_skill'),
        'artifact': ('产物', 'get_artifact'),
    }
    for ref in ctx.workspace_refs:
        if reference := reference_tools.get(ref.get('kind')):
            label, tool_name = reference
            lines.append(f'当前引用{label}：#{ref["id"]}；先用 {tool_name} 读取该引用，再处理任务')
    return '\n'.join(lines)
