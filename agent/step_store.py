import hashlib
import json

from typing import Any

from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai_harness.step_persistence import (
    ContinuableSnapshot,
    RunRecord,
    StepEvent,
    ToolEffectRecord,
)
from sqlalchemy.exc import IntegrityError

from backend.database.db import async_db_session
from backend.plugin.ai_buddy.crud.crud_step_event import ai_buddy_step_event_dao
from backend.plugin.ai_buddy.crud.crud_step_message import ai_buddy_step_message_dao
from backend.plugin.ai_buddy.crud.crud_step_run import ai_buddy_step_run_dao
from backend.plugin.ai_buddy.crud.crud_step_snapshot import ai_buddy_step_snapshot_dao
from backend.plugin.ai_buddy.crud.crud_step_tool_effect import ai_buddy_step_tool_effect_dao
from backend.plugin.ai_buddy.model.step_event import AIBuddyStepEvent
from backend.plugin.ai_buddy.model.step_message import AIBuddyStepMessage
from backend.plugin.ai_buddy.model.step_run import AIBuddyStepRun
from backend.plugin.ai_buddy.model.step_snapshot import AIBuddyStepSnapshot
from backend.plugin.ai_buddy.model.step_tool_effect import AIBuddyStepToolEffect
from backend.plugin.ai_buddy.utils.media_store import decode_model_message_payloads, encode_model_message_payloads


def _run_record(row: AIBuddyStepRun) -> RunRecord:
    return RunRecord(
        run_id=row.run_id,
        conversation_id=row.conversation_id,
        parent_run_id=row.parent_run_id,
        agent_name=row.agent_name,
        metadata=dict(row.run_metadata or {}),
        started_at=row.started_time,
        registration_id=row.registration_id,
    )


def _step_event(row: AIBuddyStepEvent) -> StepEvent:
    return StepEvent(
        run_id=row.run_id,
        kind=row.kind,
        step_index=row.step_index,
        timestamp=row.event_time,
        conversation_id=row.conversation_id,
        parent_run_id=row.parent_run_id,
        agent_name=row.agent_name,
        tool_call_id=row.tool_call_id,
        tool_name=row.tool_name,
        error=row.error,
        metadata=dict(row.event_metadata or {}),
        idempotency_key=row.idempotency_key,
    )


def _tool_effect(row: AIBuddyStepToolEffect) -> ToolEffectRecord:
    return ToolEffectRecord(
        tool_call_id=row.tool_call_id,
        tool_name=row.tool_name,
        run_id=row.run_id,
        status=row.status,
        started_at=row.started_time,
        ended_at=row.ended_time,
        idempotency_key=row.idempotency_key,
        effect_summary=row.effect_summary,
    )


class AIBuddyStepStore:
    """基于 SQLAlchemy 的步骤持久化存储，同时兼容 MySQL 与 PostgreSQL"""

    async def register_run(self, record: RunRecord) -> None:
        """
        登记运行，已存在的运行 ID 视为重复注册

        :param record: 运行记录
        :return:
        """
        row = AIBuddyStepRun(
            run_id=record.run_id,
            started_time=record.started_at,
            conversation_id=record.conversation_id,
            parent_run_id=record.parent_run_id,
            agent_name=record.agent_name,
            run_metadata=dict(record.metadata),
            registration_id=record.registration_id,
        )
        try:
            async with async_db_session.begin() as db:
                await ai_buddy_step_run_dao.create(db, row)
        except IntegrityError as exc:
            raise ValueError(f'run_id {record.run_id!r} is already in the store') from exc

    async def get_run(self, *, run_id: str) -> RunRecord | None:
        """
        获取运行记录

        :param run_id: 运行 ID
        :return:
        """
        async with async_db_session() as db:
            row = await ai_buddy_step_run_dao.get_by_run_id(db, run_id)
        return _run_record(row) if row else None

    async def list_runs(
        self, *, parent_run_id: str | None = None, conversation_id: str | None = None
    ) -> list[RunRecord]:
        """
        按开始时间升序列出运行记录

        :param parent_run_id: 父运行 ID
        :param conversation_id: 对话 ID
        :return:
        """
        async with async_db_session() as db:
            rows = await ai_buddy_step_run_dao.get_list(
                db, parent_run_id=parent_run_id, conversation_id=conversation_id
            )
        return [_run_record(row) for row in rows]

    async def append_event(self, event: StepEvent) -> None:
        """
        追加事件，相同边界幂等键的重试会被忽略

        :param event: 步骤事件
        :return:
        """
        row = AIBuddyStepEvent(
            run_id=event.run_id,
            kind=event.kind,
            step_index=event.step_index,
            event_time=event.timestamp,
            conversation_id=event.conversation_id,
            parent_run_id=event.parent_run_id,
            agent_name=event.agent_name,
            tool_call_id=event.tool_call_id,
            tool_name=event.tool_name,
            error=event.error,
            event_metadata=dict(event.metadata),
            idempotency_key=event.idempotency_key,
        )
        try:
            async with async_db_session.begin() as db:
                if event.idempotency_key and await ai_buddy_step_event_dao.get_by_key(
                    db, event.run_id, event.idempotency_key
                ):
                    return
                await ai_buddy_step_event_dao.create(db, row)
        except IntegrityError:
            if event.idempotency_key is None:
                raise

    async def list_events(self, *, run_id: str) -> list[StepEvent]:
        """
        按写入顺序列出运行事件

        :param run_id: 运行 ID
        :return:
        """
        async with async_db_session() as db:
            rows = await ai_buddy_step_event_dao.get_all(db, run_id)
        return [_step_event(row) for row in rows]

    async def save_snapshot(self, snapshot: ContinuableSnapshot) -> None:
        """
        保存快照，消息内容按摘要去重，二进制附件外置到对象存储

        :param snapshot: 可恢复快照
        :return:
        """
        payloads = ModelMessagesTypeAdapter.dump_python(snapshot.messages, mode='json')
        contents = [
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in await encode_model_message_payloads(payloads, conversation_id=snapshot.conversation_id)
        ]
        refs = [hashlib.sha256(content.encode()).hexdigest() for content in contents]
        row = AIBuddyStepSnapshot(
            run_id=snapshot.run_id,
            step_index=snapshot.step_index,
            snapshot_time=snapshot.timestamp,
            state=snapshot.state,
            message_refs=refs,
            conversation_id=snapshot.conversation_id,
            parent_run_id=snapshot.parent_run_id,
            agent_name=snapshot.agent_name,
            idempotency_key=snapshot.idempotency_key,
        )
        try:
            async with async_db_session.begin() as db:
                if snapshot.idempotency_key and await ai_buddy_step_snapshot_dao.get_by_key(
                    db, snapshot.run_id, snapshot.idempotency_key
                ):
                    return
                existing = {item.sha256 for item in await ai_buddy_step_message_dao.get_by_sha256s(db, set(refs))}
                for digest, content in dict(zip(refs, contents, strict=True)).items():
                    if digest in existing:
                        continue
                    try:
                        async with db.begin_nested():
                            await ai_buddy_step_message_dao.create(
                                db, AIBuddyStepMessage(sha256=digest, content=content)
                            )
                    except IntegrityError:
                        # 并发写入了相同内容，无需重复保存
                        continue
                await ai_buddy_step_snapshot_dao.create(db, row)
        except IntegrityError:
            if snapshot.idempotency_key is None:
                raise

    async def latest_snapshot(self, *, run_id: str, include_interrupted: bool = False) -> ContinuableSnapshot | None:
        """
        获取最新快照，默认只返回已结算的快照

        :param run_id: 运行 ID
        :param include_interrupted: 是否包含中断快照
        :return:
        """
        async with async_db_session() as db:
            row = await ai_buddy_step_snapshot_dao.get_latest(db, run_id, include_interrupted=include_interrupted)
            if row is None:
                return None
            stored = {
                item.sha256: item.content
                for item in await ai_buddy_step_message_dao.get_by_sha256s(db, set(row.message_refs))
            }
        payloads: list[Any] = [json.loads(stored[ref]) for ref in row.message_refs]
        messages = ModelMessagesTypeAdapter.validate_python(await decode_model_message_payloads(payloads))
        return ContinuableSnapshot(
            run_id=row.run_id,
            step_index=row.step_index,
            messages=messages,
            conversation_id=row.conversation_id,
            parent_run_id=row.parent_run_id,
            agent_name=row.agent_name,
            timestamp=row.snapshot_time,
            state=row.state,
            idempotency_key=row.idempotency_key,
        )

    async def record_tool_effect(self, record: ToolEffectRecord) -> None:
        """
        写入或更新工具调用的副作用台账

        :param record: 台账记录
        :return:
        """
        async with async_db_session.begin() as db:
            row = await ai_buddy_step_tool_effect_dao.get_by_call_id(db, record.run_id, record.tool_call_id)
            if row is None:
                await ai_buddy_step_tool_effect_dao.create(
                    db,
                    AIBuddyStepToolEffect(
                        run_id=record.run_id,
                        tool_call_id=record.tool_call_id,
                        tool_name=record.tool_name,
                        status=record.status,
                        started_time=record.started_at,
                        ended_time=record.ended_at,
                        idempotency_key=record.idempotency_key,
                        effect_summary=record.effect_summary,
                    ),
                )
                return
            row.tool_name = record.tool_name
            row.status = record.status
            row.started_time = record.started_at
            row.ended_time = record.ended_at
            row.idempotency_key = record.idempotency_key
            row.effect_summary = record.effect_summary

    async def get_tool_effect(self, *, run_id: str, tool_call_id: str) -> ToolEffectRecord | None:
        """
        获取工具调用的副作用台账

        :param run_id: 运行 ID
        :param tool_call_id: 工具调用 ID
        :return:
        """
        async with async_db_session() as db:
            row = await ai_buddy_step_tool_effect_dao.get_by_call_id(db, run_id, tool_call_id)
        return _tool_effect(row) if row else None

    async def list_unresolved_tool_effects(self, *, run_id: str) -> list[ToolEffectRecord]:
        """
        列出崩溃后状态未知的工具调用

        :param run_id: 运行 ID
        :return:
        """
        async with async_db_session() as db:
            rows = await ai_buddy_step_tool_effect_dao.get_unresolved(db, run_id)
        return [_tool_effect(row) for row in rows]


ai_buddy_step_store = AIBuddyStepStore()
