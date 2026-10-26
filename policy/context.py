from dataclasses import dataclass

from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyChatGenerationType,
    AIBuddyPermissionMode,
    AIBuddyProviderType,
)


@dataclass(frozen=True, slots=True)
class AIBuddyInvocationContext:
    """AI 调用策略上下文"""

    provider_id: int
    provider_type: AIBuddyProviderType
    provider_name: str
    model_pk: int
    model_id: str
    user_id: int
    is_superuser: bool = False
    mcp_ids: tuple[int, ...] = ()
    generation_type: AIBuddyChatGenerationType | None = None
    conversation_id: str | None = None
    agent_mode: AIBuddyAgentMode = AIBuddyAgentMode.work
    permission_mode: AIBuddyPermissionMode | None = None
