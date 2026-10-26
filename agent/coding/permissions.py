from backend.plugin.ai_buddy.enums import AIBuddyPermissionMode

_MUTATING_TOOLS = frozenset({'write', 'edit', 'bash', 'bash_background', 'bash_task_stop', 'write_artifact'})


def is_mutating_tool(name: str) -> bool:
    """
    判断工具是否会改动工作区或外部资源

    :param name: 工具名称
    :return:
    """
    return name in _MUTATING_TOOLS or name.startswith('mcp_')


def requires_approval(*, permission_mode: AIBuddyPermissionMode, tool_name: str) -> bool:
    """
    当前权限模式是否需要用户批准该工具

    :param permission_mode: 权限模式
    :param tool_name: 工具名称
    :return:
    """
    if permission_mode != AIBuddyPermissionMode.ask:
        return False
    return is_mutating_tool(tool_name)
