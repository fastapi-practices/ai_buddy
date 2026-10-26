from pydantic_ai.tools import ToolDefinition

from backend.plugin.ai_buddy.enums import AIBuddyToolPolicy


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


def is_mcp_tool(tool_def: ToolDefinition) -> bool:
    """
    按后端附加的来源标记识别 MCP 工具

    :param tool_def: 工具定义
    :return:
    """
    return (tool_def.metadata or {}).get('ai_buddy_source') == 'mcp'
