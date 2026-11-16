from collections.abc import Mapping

from backend.plugin.ai_buddy.enums import AIBuddyToolPolicy


def _normalize_policy(value: str | AIBuddyToolPolicy | None) -> AIBuddyToolPolicy | None:
    """
    将原始策略转换为枚举

    :param value: 原始策略
    :return:
    """
    if value is None:
        return None
    try:
        return AIBuddyToolPolicy(str(value).strip().lower())
    except ValueError:
        return None


def merge_tool_policies(
    *,
    profile_policies: Mapping[str, str | AIBuddyToolPolicy] | None,
    runtime_policies: Mapping[str, str | AIBuddyToolPolicy] | None,
) -> dict[str, AIBuddyToolPolicy]:
    """
    合并服务端预设与本轮显式策略

    合并规则：任意 deny 永远优先；同工具的具体策略优先于通配策略；本轮显式策略优先于预设策略
    deny 永远不能被客户端覆盖

    :param profile_policies: 权限预设策略
    :param runtime_policies: 本轮显式策略
    :return:
    """
    profile = {
        key: value for key, raw in (profile_policies or {}).items() if (value := _normalize_policy(raw)) is not None
    }
    runtime = {
        key: value for key, raw in (runtime_policies or {}).items() if (value := _normalize_policy(raw)) is not None
    }
    merged: dict[str, AIBuddyToolPolicy] = {}
    for tool_name in {key for key in profile if key != '*'} | {key for key in runtime if key != '*'}:
        profile_policy = profile.get(tool_name)
        runtime_policy = runtime.get(tool_name)
        if profile_policy == AIBuddyToolPolicy.deny or runtime_policy == AIBuddyToolPolicy.deny:
            merged[tool_name] = AIBuddyToolPolicy.deny
        elif runtime_policy is not None:
            merged[tool_name] = runtime_policy
        elif profile_policy is not None:
            merged[tool_name] = profile_policy
    profile_default = profile.get('*')
    runtime_default = runtime.get('*')
    if profile_default == AIBuddyToolPolicy.deny or runtime_default == AIBuddyToolPolicy.deny:
        merged['*'] = AIBuddyToolPolicy.deny
    elif runtime_default is not None:
        merged['*'] = runtime_default
    elif profile_default is not None:
        merged['*'] = profile_default
    return merged
