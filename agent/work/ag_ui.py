from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, override

import jsonpatch

from ag_ui.core import (
    ActivityDeltaEvent,
    ActivityMessage,
    ActivitySnapshotEvent,
    BaseEvent,
    CustomEvent,
    RunErrorEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    SubagentErrorEvent,
    SubagentFinishedEvent,
    SubagentStartedEvent,
)
from pydantic import TypeAdapter
from pydantic_ai import CapabilityEvent
from pydantic_ai.messages import TextPart
from pydantic_ai.ui.ag_ui import AGUIAdapter, AGUIEventStream

from backend.plugin.ai_buddy.dataclasses import ChatAgentDeps
from backend.plugin.ai_buddy.utils.ag_ui import encode_ag_ui_event
from backend.plugin.ai_buddy.utils.citation import text_part_citations
from backend.plugin.ai_buddy.utils.run_error import build_run_error_payload


def lifecycle_payload(event: CapabilityEvent) -> tuple[str, dict[str, Any]] | None:
    """
    只向客户端公开计划和子代理的真实能力事件

    :param event: 事件数据
    :return:
    """
    if event.kind == 'buddy_input.request':
        return 'buddy.user_input', dict(event.request)
    if event.kind.startswith('planning.'):
        name = 'buddy.planning'
    elif event.kind.startswith('sub_agents.'):
        name = 'buddy.subagent'
    elif event.kind.startswith('buddy_compaction.'):
        name = 'buddy.compaction'
    elif event.kind.startswith('buddy_tasks.'):
        name = 'buddy.delegation'
    else:
        return None
    payload = TypeAdapter(dict[str, Any]).dump_python(asdict(event), mode='json')
    payload['kind'] = event.kind
    return name, payload


@dataclass
class BuddyAGUIEventStream(AGUIEventStream):
    """保留官方协议行为并显式转发可展示的能力事件"""

    lifecycle_events: list[dict[str, Any]] = field(default_factory=list)
    deps: ChatAgentDeps | None = None
    activities: dict[str, ActivityMessage] = field(default_factory=dict)

    @override
    async def on_error(self, error: Exception) -> AsyncIterator[BaseEvent]:
        """
        保留 SDK 错误终态并公开统一错误分类

        :param error: 模型或运行异常
        :return:
        """
        payload = build_run_error_payload(error)
        async for event in super().on_error(error):
            if isinstance(event, RunErrorEvent):
                event = event.model_copy(
                    update={'message': payload['message'], 'code': payload.get('code'), 'raw_event': payload}
                )
            yield event

    @override
    def encode_event(self, event: BaseEvent) -> str:
        """
        统一校验工作和生图事件的线协议

        :param event: 执行事件
        :return:
        """
        match event:
            case StateSnapshotEvent() if self.deps is not None:
                self.deps.state = deepcopy(event.snapshot)
            case StateDeltaEvent() if self.deps is not None:
                self.deps.state = jsonpatch.apply_patch(self.deps.state, event.delta, in_place=False)
            case ActivitySnapshotEvent():
                if event.replace is not False or event.message_id not in self.activities:
                    self.activities[event.message_id] = ActivityMessage(
                        id=event.message_id, activity_type=event.activity_type, content=event.content
                    )
            case ActivityDeltaEvent():
                activity = self.activities[event.message_id]
                content = jsonpatch.apply_patch(activity.content, event.patch, in_place=False)
                self.activities[event.message_id] = ActivityMessage(
                    id=activity.id, activity_type=event.activity_type, content=content
                )
        return encode_ag_ui_event(event)

    @override
    async def handle_text_end(self, part: TextPart, followed_by_text: bool = False) -> AsyncIterator[BaseEvent]:
        """
        在原生文本结束时保留供应商返回的网页引用

        :param part: 文本片段
        :param followed_by_text: 是否紧接下一个文本片段
        :return:
        """
        sources = text_part_citations([part])
        if sources:
            yield CustomEvent(
                name='buddy.citations',
                value={'message_id': self.message_id, 'sources': [source.model_dump() for source in sources]},
            )
        async for event in super().handle_text_end(part, followed_by_text):
            yield event

    async def handle_capability_event(self, event: CapabilityEvent) -> AsyncIterator[BaseEvent]:
        """
        将能力生命周期事件转换为 AG-UI 活动事件

        :param event: 事件数据
        :return:
        """
        converted = lifecycle_payload(event)
        if converted is None:
            return
        name, value = converted
        value['message_id'] = self.message_id
        self.lifecycle_events.append({'name': name, 'value': value})
        if len(self.lifecycle_events) > 500:
            del self.lifecycle_events[0]
        if name == 'buddy.subagent':
            subagent_run_id = value.get('task_id') or event.tool_call_id
            if not subagent_run_id:
                raise ValueError('子代理事件缺少任务或工具调用标识')
            value['task_id'] = subagent_run_id
            if event.kind == 'sub_agents.delegation_start':
                yield SubagentStartedEvent(
                    subagent_run_id=subagent_run_id,
                    name=value['agent_name'],
                    description=value.get('task'),
                    parent_tool_call_id=event.tool_call_id,
                    parent_message_id=self.message_id,
                    parent_subagent_run_id=value.get('parent_id'),
                    metadata={'buddy': value},
                )
            elif value.get('outcome') == 'ok':
                yield SubagentFinishedEvent(
                    subagent_run_id=subagent_run_id,
                    result=value.get('output'),
                    metadata={'buddy': value},
                )
            else:
                yield SubagentErrorEvent(
                    subagent_run_id=subagent_run_id,
                    message=value.get('output') or '子代理执行失败',
                    code=value.get('outcome'),
                    metadata={'buddy': value},
                )
            return
        yield CustomEvent(name=name, value=value)


@dataclass
class BuddyAGUIAdapter(AGUIAdapter):
    """为同一次运行共享能力事件记录"""

    lifecycle_events: list[dict[str, Any]] = field(default_factory=list)
    deps: ChatAgentDeps | None = None
    activities: dict[str, ActivityMessage] = field(default_factory=dict)

    def build_event_stream(self) -> BuddyAGUIEventStream:
        """构建支持能力生命周期通知的 AG-UI 事件流"""
        return BuddyAGUIEventStream(
            self.run_input,
            accept=self.accept,
            ag_ui_version=self.ag_ui_version,
            lifecycle_events=self.lifecycle_events,
            deps=self.deps,
            activities=self.activities,
        )
