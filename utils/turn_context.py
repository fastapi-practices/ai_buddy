from typing import Any

from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyOrigin
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam, AIBuddyForwardedPropsParam


def build_turn_context(
    *,
    forwarded_props: AIBuddyForwardedPropsParam,
    origin: AIBuddyOrigin = AIBuddyOrigin.web,
) -> dict[str, Any]:
    """
    生成本轮实际使用的组合，不写回对话偏好

    :param forwarded_props: 本轮扩展参数
    :param origin: 本轮来源
    :return:
    """
    workspace_ref = None
    workspace_id = None
    mcp_ids: list[int] = []
    agent_mode = None
    permission_mode = None
    acp_runner = None
    acp_runner_name = None
    thinking = None
    web_search = None
    execution_backend = None
    if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam):
        mcp_ids = list(forwarded_props.mcp_ids or [])
        agent_mode = forwarded_props.agent_mode
        permission_mode = forwarded_props.permission_mode
        acp_runner = forwarded_props.acp_runner
        acp_runner_name = forwarded_props.acp_runner_name
        thinking = forwarded_props.thinking
        web_search = forwarded_props.web_search
        execution_backend = forwarded_props.execution_backend
        workspace_id = forwarded_props.workspace_id if forwarded_props.agent_mode == AIBuddyAgentMode.coding else None
        if forwarded_props.workspace_ref is not None:
            workspace_ref = {
                'kind': forwarded_props.workspace_ref.kind,
                'id': forwarded_props.workspace_ref.id,
            }
    return {
        'origin': origin,
        'provider_id': forwarded_props.provider_id,
        'model_id': forwarded_props.model_id,
        'generation_type': forwarded_props.generation_type,
        'agent_mode': agent_mode,
        'execution_backend': execution_backend,
        'thinking': thinking,
        'web_search': web_search,
        'mcp_ids': mcp_ids,
        'workspace_ref': workspace_ref,
        'workspace_id': workspace_id,
        'permission_mode': permission_mode,
        'acp_runner': acp_runner,
        'acp_runner_name': acp_runner_name,
        **(
            {'quote': forwarded_props.quote.model_dump(by_alias=True, exclude_none=True)}
            if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam) and forwarded_props.quote is not None
            else {}
        ),
    }
