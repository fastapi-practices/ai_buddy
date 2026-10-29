import asyncio
import contextlib
import json

from dataclasses import dataclass
from typing import Any

import anyio

from pydantic_ai import AgentRunResult, CapabilityEvent, RunContext
from pydantic_ai.capabilities import WrapRunHandler
from pydantic_ai.output import OutputContext
from pydantic_ai_harness.subagents import DelegationReports, DelegationTaskEvent, DelegationTasks

from backend.database.redis import redis_client
from backend.plugin.ai_buddy.dataclasses import ChatAgentDeps
from backend.plugin.ai_buddy.service.delegation_service import ai_buddy_delegation_service


@dataclass(kw_only=True)
class BuddyDelegationChanged(CapabilityEvent, namespace='buddy_tasks', name='changed'):
    """本轮子代理状态快照，不包含内部消息历史"""

    run_id: str
    active: bool
    tasks: list[dict[str, Any]]


class BuddyDelegationReports(DelegationReports):
    """限定在一轮内的后台委派、报告回流与跨进程控制"""

    def __init__(self, *, conversation_id: str) -> None:
        """
        创建由本轮独占的委派任务所有者

        :param conversation_id: 对话 ID
        :return:
        """
        super().__init__(DelegationTasks(observer=self.observe), conversation_id=conversation_id)
        self.context: RunContext[ChatAgentDeps] | None = None
        self.active = False
        self.key = ''
        self.last_snapshot = ''
        self.changed = asyncio.Event()

    async def wrap_run(self, ctx: RunContext[ChatAgentDeps], *, handler: WrapRunHandler) -> AgentRunResult[Any]:
        """
        关闭所有子任务后再释放主模型和工作区

        :param ctx: 运行上下文
        :param handler: SDK 运行处理器
        :return:
        """
        self.context = ctx
        self.key = ai_buddy_delegation_service.key(conversation_id=self.conversation_id, run_id=ctx.run_id)
        self.active = True
        monitor = None
        try:
            async with self.owner.opened():
                with self.owner.bind():
                    await self.publish()
                    monitor = asyncio.create_task(self.control(), name=f'buddy-delegations-{ctx.run_id}')
                    return await super().wrap_run(ctx, handler=handler)
        finally:
            if monitor is not None:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            self.active = False
            with anyio.move_on_after(5, shield=True):
                await self.publish()
                await redis_client.delete(f'{self.key}:commands')

    async def after_output_process(
        self,
        ctx: RunContext[ChatAgentDeps],
        *,
        output_context: OutputContext,
        output: object,
    ) -> object:
        """
        等待本轮子任务并在最终回复前让 SDK 消费报告

        :param ctx: 运行上下文
        :param output_context: 输出上下文
        :param output: 模型输出
        :return:
        """
        if not ctx.partial_output:
            while True:
                self.changed.clear()
                if not any(task.status == 'running' for task in self.owner.records.values()):
                    break
                # 状态通知兜底：即使通知丢失也每秒复查一次，避免永久挂起
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.changed.wait(), timeout=1)
            self.owner.queue_reports(conversation_id=self.conversation_id, parent_id=None)
        return output

    async def observe(self, event: DelegationTaskEvent) -> None:
        """
        转发变化的任务状态，忽略逐 token 子事件

        :param event: SDK 子任务事件
        :return:
        """
        self.changed.set()
        if event.event is None:
            await self.publish()

    async def publish(self) -> None:
        """向界面和跨进程控制通道发布同一份状态"""
        if self.context is None:
            return
        tasks = [
            {
                'task_id': task.id,
                'agent_name': task.agent_name,
                'parent_id': task.parent_id,
                'status': task.status,
                'outcome': task.outcome,
                'background': task.background,
                'output': task.output[:4000],
            }
            for task in self.owner.records.values()
        ]
        payload = {'run_id': self.context.run_id, 'active': self.active, 'tasks': tasks}
        snapshot = json.dumps(payload, ensure_ascii=False)
        if snapshot != self.last_snapshot:
            await redis_client.set(self.key, snapshot, ex=3600)
            self.last_snapshot = snapshot
            await self.context.emit(BuddyDelegationChanged(**payload))

    async def control(self) -> None:
        """串行处理本轮引导与停止命令并返回确认"""
        while True:
            raw = await redis_client.lpop(f'{self.key}:commands')
            if raw is None:
                await asyncio.sleep(0.1)
                continue
            command = json.loads(raw)
            task = self.owner.records.get(command['task_id'])
            accepted = task is not None and task.status == 'running' and self.active
            if accepted:
                if command['action'] == 'stop':
                    await self.owner.cancel(task.id)
                else:
                    accepted = self.owner.steer(task.id, command['text'])
            await redis_client.set(f'{self.key}:ack:{command["id"]}', 'ok' if accepted else 'finished', ex=30)
            await self.publish()
