from __future__ import annotations

from typing import TYPE_CHECKING

from backend.plugin.ai_buddy.agent.coding.protocol.pydantic_ai.session import PydanticAICodingSession
from backend.plugin.ai_buddy.agent.coding.tools import (
    CODER_OWNED_TOOLS,
    DESKTOP_UNSUPPORTED_TOOLS,
    build_builtin_tools,
)
from backend.plugin.ai_buddy.enums import AIBuddyExecutionBackend

if TYPE_CHECKING:
    from backend.plugin.ai_buddy.agent.coding.protocol.base import CodingHostSession
    from backend.plugin.ai_buddy.dataclasses import BoundAgentTool, CodingHostSpec


class PydanticAICodingProtocolAdapter:
    """Pydantic AI 编码宿主协议适配器"""

    name = 'pydantic_ai'

    @staticmethod
    async def open_session(*, spec: CodingHostSpec) -> CodingHostSession:
        """
        打开 Pydantic AI 编码宿主

        :param spec: 宿主规格
        :return:
        """
        builtins = build_builtin_tools(spec.run_context) if spec.run_context.sandbox is not None else []
        merged: dict[str, BoundAgentTool] = {item.spec.name: item for item in builtins}
        for item in spec.buddy_tools:
            merged[item.spec.name] = item
        sandbox = spec.run_context.sandbox
        if (
            sandbox is not None
            and sandbox.execution_backend == AIBuddyExecutionBackend.sandbox
            and not spec.run_context.acp_runner_enabled
        ):
            for name in CODER_OWNED_TOOLS:
                merged.pop(name, None)
        elif sandbox is not None and sandbox.execution_backend == AIBuddyExecutionBackend.local:
            for name in DESKTOP_UNSUPPORTED_TOOLS:
                merged.pop(name, None)
        return PydanticAICodingSession(spec=spec, tools=list(merged.values()))


pydantic_ai_coding_protocol_adapter = PydanticAICodingProtocolAdapter()
