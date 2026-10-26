import json

from typing import Any

from backend.plugin.ai_buddy.utils.ag_ui import encode_ag_ui_event


class CodingEventStream:
    """将编码宿主事件转换为桌面端共用的 AG-UI 事件"""

    def __init__(self, *, conversation_id: str, run_id: str, message_id: str) -> None:
        """初始化编码对话的 AG-UI 事件标识

        :param conversation_id: 对话 ID
        :param run_id: 运行 ID
        :param message_id: 消息 ID
        :return:
        """
        self.conversation_id = conversation_id
        self.run_id = run_id
        self.message_id = message_id
        self._tools: set[str] = set()
        self._reasoning_open = False
        self._reasoning_index = 0
        self._reasoning_id = ''
        self.activities: dict[str, dict[str, Any]] = {}

    def _content_events(self, *, event: str, delta: str) -> list[dict[str, Any]]:
        """
        转换正文与推理增量，推理块首次出现时补全起始事件

        :param event: 事件名称
        :param delta: 文本增量
        :return:
        """
        events: list[dict[str, Any]] = []
        if event == 'thinking' and not self._reasoning_open:
            self._reasoning_index += 1
            self._reasoning_id = f'{self.message_id}:reasoning:{self._reasoning_index}'
            self._reasoning_open = True
            events.extend([
                {'type': 'REASONING_START', 'messageId': self._reasoning_id},
                {'type': 'REASONING_MESSAGE_START', 'messageId': self._reasoning_id, 'role': 'reasoning'},
            ])
        events.append({
            'type': 'REASONING_MESSAGE_CONTENT' if event == 'thinking' else 'TEXT_MESSAGE_CONTENT',
            'messageId': self._reasoning_id if event == 'thinking' else self.message_id,
            'delta': delta,
        })
        return events

    def _tool_start_events(self, *, data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        转换工具调用开始事件，同一调用只发送一次

        :param data: 工具调用数据
        :return:
        """
        call_id = str(data['call_id'])
        if call_id in self._tools:
            return []
        self._tools.add(call_id)
        return [
            {
                'type': 'TOOL_CALL_START',
                'toolCallId': call_id,
                'toolCallName': data['name'],
                'parentMessageId': self.message_id,
            },
            {
                'type': 'TOOL_CALL_ARGS',
                'toolCallId': call_id,
                'delta': json.dumps(data.get('arguments', {}), ensure_ascii=False, default=str),
            },
            {'type': 'TOOL_CALL_END', 'toolCallId': call_id},
        ]

    def encode(self, event: str, data: dict[str, Any]) -> str:
        """将编码运行事件转换为 AG-UI 事件帧

        :param event: 事件数据
        :param data: 输入数据
        :return:
        """
        close_reasoning = self._reasoning_open and event in {'text', 'tool_start', 'done', 'error'}
        events: list[dict[str, Any]] = (
            [
                {'type': 'REASONING_MESSAGE_END', 'messageId': self._reasoning_id},
                {'type': 'REASONING_END', 'messageId': self._reasoning_id},
            ]
            if close_reasoning
            else []
        )
        self._reasoning_open = self._reasoning_open and not close_reasoning
        if event == 'start':
            events = [
                {'type': 'RUN_STARTED', 'threadId': self.conversation_id, 'runId': self.run_id},
                {'type': 'TEXT_MESSAGE_START', 'messageId': self.message_id, 'role': 'assistant'},
            ]
        elif event in {'text', 'thinking'}:
            events.extend(self._content_events(event=event, delta=data['delta']))
        elif event in {'citations', 'approval', 'approval_resolved'}:
            events = [
                {
                    'type': 'CUSTOM',
                    'name': 'buddy.citations' if event == 'citations' else f'buddy.coding.{event}',
                    'value': {**data, 'message_id': self.message_id},
                }
            ]
        elif event == 'tool_start':
            events.extend(self._tool_start_events(data=data))
        elif event == 'tool_result':
            events = [
                {
                    'type': 'TOOL_CALL_RESULT',
                    'toolCallId': data['call_id'],
                    'messageId': f'{self.message_id}:{data["call_id"]}',
                    'role': 'tool',
                    'content': data['result'],
                }
            ]
        elif event == 'ag_ui':
            events = [data]
            if data.get('type') == 'ACTIVITY_SNAPSHOT':
                self.activities[data['messageId']] = {
                    'id': data['messageId'],
                    'role': 'activity',
                    'activityType': data['activityType'],
                    'content': data['content'],
                }
        elif event == 'done':
            events.extend([
                {'type': 'TEXT_MESSAGE_END', 'messageId': self.message_id},
                {
                    'type': 'RUN_FINISHED',
                    'threadId': self.conversation_id,
                    'runId': self.run_id,
                    'result': {'status': data['status']},
                },
            ])
        elif event == 'error':
            events.append({'type': 'RUN_ERROR', 'message': data['message'], 'code': data.get('code'), 'rawEvent': data})
        return ''.join(encode_ag_ui_event(item) for item in events)
