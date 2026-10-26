from typing import Any

from pydantic_ai import Agent, BinaryImage, DeferredToolRequests, ModelRequest, ModelResponse

from backend.plugin.ai_buddy.dataclasses import ChatAgentDeps

type ChatModelMessage = ModelRequest | ModelResponse
type ChatAgentOutput = BinaryImage | str | DeferredToolRequests
type ChatAgent = Agent[ChatAgentDeps, Any]
