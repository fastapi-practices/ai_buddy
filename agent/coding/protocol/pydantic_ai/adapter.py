from __future__ import annotations

from typing import TYPE_CHECKING

from backend.plugin.ai_buddy.agent.coding.protocol.pydantic_ai.session import PydanticAICodingSession
from backend.plugin.ai_buddy.agent.coding.tools import BoundAgentTool, build_builtin_tools

if TYPE_CHECKING:
    from backend.plugin.ai_buddy.agent.coding.protocol.base import CodingHostSession, CodingHostSpec


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
        return PydanticAICodingSession(spec=spec, tools=list(merged.values()))


pydantic_ai_coding_protocol_adapter = PydanticAICodingProtocolAdapter()
