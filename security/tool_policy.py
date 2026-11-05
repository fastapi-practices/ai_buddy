from collections.abc import Mapping

from pydantic_ai.tools import ToolDefinition

from backend.plugin.ai_buddy.enums import AIBuddyToolPolicy

# 写入持久资源的工具，默认需要用户确认并纳入高风险判定
RESOURCE_WRITE_TOOLS = frozenset({
    'create_cron',
    'set_cron_enabled',
    'delete_cron',
    'create_assistant',
    'update_assistant',
    'create_expert',
    'update_expert',
    'create_skill',
    'update_skill',
})

# 在沙箱中执行命令和交付文件的工具，默认需要用户确认
SANDBOX_CONFIRM_TOOLS = frozenset({'bash', 'deliver_file'})

# 组合工具会间接触发依赖工具，依赖项的限制必须向上继承
TOOL_POLICY_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    'run_tests': ('bash', 'write_artifact'),
    'smart_search': ('bash', 'read'),
}

_POLICY_PRIORITY = {
    AIBuddyToolPolicy.allow: 0,
    AIBuddyToolPolicy.ask: 1,
    AIBuddyToolPolicy.deny: 2,
}


def resolve_tool_policy(
    *,
    tool_name: str,
    policies: dict[str, str] | None,
    default: AIBuddyToolPolicy = AIBuddyToolPolicy.allow,
) -> AIBuddyToolPolicy:
    """
    按显式策略解析工具允许 / 询问 / 拒绝，不靠英文动词猜测

    :param tool_name: 工具全名或短名
    :param policies: 工具名到策略的映射
    :param default: 未列出时的默认策略
    :return:
    """
    if not policies:
        return default
    candidates = [tool_name]
    if '_' in tool_name:
        candidates.append(tool_name.rsplit('_', 1)[-1])
        parts = tool_name.split('_', 2)
        if len(parts) >= 3:
            candidates.append(parts[-1])
    for name in candidates:
        raw = policies.get(name) or policies.get(name.lower())
        if raw is None:
            continue
        try:
            return AIBuddyToolPolicy(str(raw).strip().lower())
        except ValueError:
            continue
    return default


def resolve_tool_policy_with_dependencies(
    *,
    tool_name: str,
    policies: dict[str, str] | None,
    default: AIBuddyToolPolicy = AIBuddyToolPolicy.allow,
    dependency_defaults: Mapping[str, AIBuddyToolPolicy] | None = None,
) -> AIBuddyToolPolicy:
    """
    解析工具及其依赖项中最严格的策略

    :param tool_name: 工具全名或短名
    :param policies: 工具名到策略的映射
    :param default: 工具未列出时的默认策略
    :param dependency_defaults: 依赖工具未列出时的默认策略
    :return:
    """
    policy = resolve_tool_policy(tool_name=tool_name, policies=policies, default=default)
    dependency_defaults = dependency_defaults or {}
    for dependency in TOOL_POLICY_DEPENDENCIES.get(tool_name, ()):
        dependency_policy = resolve_tool_policy(
            tool_name=dependency,
            policies=policies,
            default=dependency_defaults.get(dependency, AIBuddyToolPolicy.allow),
        )
        policy = max(policy, dependency_policy, key=_POLICY_PRIORITY.__getitem__)
    return policy


def is_mcp_tool(tool_def: ToolDefinition) -> bool:
    """
    按后端附加的来源标记识别 MCP 工具

    :param tool_def: 工具定义
    :return:
    """
    return (tool_def.metadata or {}).get('ai_buddy_source') == 'mcp'
