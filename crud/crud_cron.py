from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.common.enums import StatusType
from backend.plugin.ai_buddy.model.cron import AIBuddyCron
from backend.plugin.ai_buddy.schema.cron import CreateAIBuddyCronParam, UpdateAIBuddyCronParam
from backend.utils.timezone import timezone


class CRUDAIBuddyCron(CRUDPlus[AIBuddyCron]):
    """AI 定时任务数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyCron | None:
        """
        获取定时任务

        :param db: 数据库会话
        :param pk: 任务 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_name(self, db: AsyncSession, user_id: int, name: str) -> AIBuddyCron | None:
        """
        通过名称获取当前用户定时任务

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 任务名称
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, name=name, deleted=0)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyCron]:
        """
        获取当前用户所有定时任务

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(db, 'id', 'desc', user_id=user_id, deleted=0)

    async def get_enabled(self, db: AsyncSession) -> Sequence[AIBuddyCron]:
        """
        获取已启用的定时任务

        :param db: 数据库会话
        :return:
        """
        return await self.select_models(db, status=StatusType.enable, deleted=0)

    async def create(self, db: AsyncSession, obj: CreateAIBuddyCronParam, user_id: int) -> AIBuddyCron:
        """
        创建定时任务

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        return await self.create_model(db, obj, user_id=user_id, flush=True)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyCronParam) -> int:
        """
        更新定时任务

        :param db: 数据库会话
        :param pk: 任务 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def update_run_result(
        self,
        db: AsyncSession,
        pk: int,
        *,
        last_run_time: datetime,
        last_status: str,
        last_error: str | None = None,
        status: int | None = None,
    ) -> int:
        """
        更新最近执行结果

        :param db: 数据库会话
        :param pk: 任务 ID
        :param last_run_time: 最近执行时间
        :param last_status: 最近执行状态
        :param last_error: 最近执行错误
        :param status: 可选状态覆盖
        :return:
        """
        payload: dict[str, object] = {
            'last_run_time': last_run_time,
            'last_status': last_status,
            'last_error': last_error,
        }
        if status is not None:
            payload['status'] = status
        return await self.update_model_by_column(db, payload, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除定时任务

        :param db: 数据库会话
        :param pk: 任务 ID
        :param user_id: 用户 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id=pk,
            user_id=user_id,
            deleted=0,
        )


ai_buddy_cron_dao: CRUDAIBuddyCron = CRUDAIBuddyCron(AIBuddyCron)
