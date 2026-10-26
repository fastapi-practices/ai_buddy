import hashlib
import json

from datetime import timedelta
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.db import async_db_session
from backend.plugin.ai_buddy.crud.crud_approval_audit import ai_buddy_approval_audit_dao
from backend.plugin.ai_buddy.enums import AIBuddyApprovalStatus
from backend.plugin.ai_buddy.model.approval_audit import AIBuddyApprovalAudit
from backend.plugin.ai_buddy.schema.approval_audit import GetAIBuddyApprovalAuditDetail
from backend.utils.timezone import timezone


class AIBuddyApprovalAuditService:
    """AI 工具审批审计服务类"""

    @staticmethod
    async def get_all(
        *, db: AsyncSession, user_id: int, before: int | None = None, limit: int = 100
    ) -> list[GetAIBuddyApprovalAuditDetail]:
        """读取当前用户的审批历史，异常退出留下的请求按到期时间展示

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param before: 上一页最小 ID
        :param limit: 返回条数
        :return:
        """
        rows = await ai_buddy_approval_audit_dao.get_all(db, user_id, before=before, limit=limit)
        now = timezone.now()
        results: list[GetAIBuddyApprovalAuditDetail] = []
        for row in rows:
            record = GetAIBuddyApprovalAuditDetail.model_validate(row)
            if (
                record.status == AIBuddyApprovalStatus.pending
                and record.expires_time is not None
                and record.expires_time <= now
            ):
                record = record.model_copy(
                    update={'status': AIBuddyApprovalStatus.expired, 'resolved_time': record.expires_time}
                )
            results.append(record)
        return results

    @staticmethod
    async def create(
        *,
        user_id: int,
        conversation_id: str,
        request_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        expires_seconds: int | None,
    ) -> None:
        """在发出审批前持久化请求，原始参数仅保存可核对摘要

        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param request_id: 审批请求 ID
        :param run_id: 运行 ID
        :param tool_call_id: 工具调用 ID
        :param tool_name: 工具名称
        :param arguments: 工具参数
        :param expires_seconds: 有效秒数
        :return:
        """
        fingerprint = hashlib.sha256(
            json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()
        ).hexdigest()
        async with async_db_session.begin() as db:
            await ai_buddy_approval_audit_dao.create(
                db,
                AIBuddyApprovalAudit(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    request_id=request_id,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments_sha256=fingerprint,
                    expires_time=(
                        timezone.now() + timedelta(seconds=expires_seconds) if expires_seconds is not None else None
                    ),
                ),
            )

    @staticmethod
    async def resolve(
        *,
        user_id: int,
        request_id: str,
        status: Literal[
            AIBuddyApprovalStatus.approved,
            AIBuddyApprovalStatus.denied,
            AIBuddyApprovalStatus.cancelled,
            AIBuddyApprovalStatus.expired,
        ],
    ) -> None:
        """持久化审批结果，数据库写入成功后才允许执行工具

        :param user_id: 用户 ID
        :param request_id: 审批请求 ID
        :param status: 审批结果
        :return:
        """
        async with async_db_session.begin() as db:
            await ai_buddy_approval_audit_dao.resolve(db, user_id, request_id, status, timezone.now())

    async def request_work(
        self,
        *,
        user_id: int,
        conversation_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        approved: bool,
    ) -> None:
        """保存可跨轮恢复的工作工具审批，重放同一调用不重复登记

        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param run_id: 发起运行 ID
        :param tool_call_id: 工具调用 ID
        :param tool_name: 工具名称
        :param arguments: 原始工具参数
        :param approved: 恢复时已获批准
        :return:
        """
        request_id = self._work_request_id(user_id=user_id, conversation_id=conversation_id, tool_call_id=tool_call_id)
        async with async_db_session() as db:
            existing = await ai_buddy_approval_audit_dao.get_by_request_id(db, user_id, request_id)
        if existing is None:
            await self.create(
                user_id=user_id,
                conversation_id=conversation_id,
                request_id=request_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
                expires_seconds=None,
            )
        if approved:
            await self.resolve(user_id=user_id, request_id=request_id, status=AIBuddyApprovalStatus.approved)

    async def resolve_work(self, *, user_id: int, conversation_id: str, decisions: dict[str, bool]) -> None:
        """在恢复工作流前保存已知审批决定，忽略不属于本对话的请求

        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param decisions: 工具调用 ID 对应的用户决定
        :return:
        """
        async with async_db_session.begin() as db:
            for tool_call_id, approved in decisions.items():
                request_id = self._work_request_id(
                    user_id=user_id, conversation_id=conversation_id, tool_call_id=tool_call_id
                )
                await ai_buddy_approval_audit_dao.resolve(
                    db,
                    user_id,
                    request_id,
                    AIBuddyApprovalStatus.approved if approved else AIBuddyApprovalStatus.denied,
                    timezone.now(),
                )

    @staticmethod
    def _work_request_id(*, user_id: int, conversation_id: str, tool_call_id: str) -> str:
        """生成跨轮恢复稳定的工作工具审批标识

        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param tool_call_id: 工具调用 ID
        :return:
        """
        return hashlib.sha256(json.dumps([user_id, conversation_id, tool_call_id]).encode()).hexdigest()


ai_buddy_approval_audit_service: AIBuddyApprovalAuditService = AIBuddyApprovalAuditService()
