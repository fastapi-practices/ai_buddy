from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai.toolsets import FunctionToolset

from backend.plugin.ai_buddy.agent.work.capabilities.builtin_toolset import get_current_time
from backend.plugin.ai_buddy.agent.work.capabilities.workspace_tools import (
    get_artifact,
    get_knowledge,
    list_artifacts,
    search_knowledge,
    write_artifact,
)
from backend.plugin.ai_buddy.dataclasses import ChatAgentDeps


@dataclass(frozen=True, slots=True)
class SubagentToolSpec:
    """子代理可选工具"""

    name: str
    category: str
    label: str
    description: str
    handler: Callable[..., Any]


SUBAGENT_TOOL_CATALOG: tuple[SubagentToolSpec, ...] = (
    SubagentToolSpec(
        name='search_knowledge',
        category='knowledge',
        label='检索知识库',
        description='按语义检索知识库，返回最相关切片',
        handler=search_knowledge,
    ),
    SubagentToolSpec(
        name='get_knowledge',
        category='knowledge',
        label='读取知识',
        description='按 ID 读取一条知识的完整内容',
        handler=get_knowledge,
    ),
    SubagentToolSpec(
        name='list_artifacts',
        category='artifact',
        label='列出产物',
        description='列出当前用户已保存的工作产物',
        handler=list_artifacts,
    ),
    SubagentToolSpec(
        name='get_artifact',
        category='artifact',
        label='读取产物',
        description='按 ID 读取一条工作产物',
        handler=get_artifact,
    ),
    SubagentToolSpec(
        name='write_artifact',
        category='artifact',
        label='写入产物',
        description='创建或更新工作产物',
        handler=write_artifact,
    ),
    SubagentToolSpec(
        name='get_current_time',
        category='misc',
        label='当前时间',
        description='获取当前时间',
        handler=get_current_time,
    ),
)


def list_subagent_tools() -> Sequence[SubagentToolSpec]:
    """返回子代理内置工具目录"""
    return SUBAGENT_TOOL_CATALOG


def build_subagent_toolset() -> FunctionToolset[ChatAgentDeps]:
    """装配子代理全部内置工具"""
    toolset: FunctionToolset[ChatAgentDeps] = FunctionToolset[ChatAgentDeps]()
    for spec in SUBAGENT_TOOL_CATALOG:
        toolset.tool(spec.handler)
    return toolset
