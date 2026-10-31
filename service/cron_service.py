from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.plugin.ai_buddy.cron.schedule import next_run_time
from backend.plugin.ai_buddy.cron.task_type import (
    CRON_MIN_INTERVAL_SECONDS,
    CRON_USER_MAX_ENABLED,
    require_cron_name,
    require_cron_prompt,
)
from backend.plugin.ai_buddy.cron.trigger import normalize_trigger, parse_date_trigger, parse_trigger
from backend.plugin.ai_buddy.crud.crud_cron import ai_buddy_cron_dao
from backend.plugin.ai_buddy.crud.crud_mcp import ai_buddy_mcp_dao
from backend.plugin.ai_buddy.model.cron import AIBuddyCron
from backend.plugin.ai_buddy.schema.cron import CreateAIBuddyCronParam, UpdateAIBuddyCronParam
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.utils.timezone import timezone


class AIBuddyCronService:
    """AI 定时任务服务类"""

    @staticmethod
    async def _normalize(
        *,
        db: AsyncSession,
        obj: CreateAIBuddyCronParam | UpdateAIBuddyCronParam,
        user_id: int,
        fallback: str,
    ) -> CreateAIBuddyCronParam | UpdateAIBuddyCronParam:
        """
        规范化定时任务字段

        :param db: 数据库会话
        :param obj: 创建或更新参数
        :param user_id: 用户 ID
        :param fallback: 名称回落值
        :return:
        """
        conversation_id = obj.conversation_id.strip()
        if not conversation_id:
            raise errors.RequestError(msg='对话 ID 不能为空')
        prompt = require_cron_prompt(obj.prompt)
        name = require_cron_name(obj.name, prompt=prompt, fallback=fallback)
        trigger = normalize_trigger(obj.trigger)
        mcp_ids: list[int] = []
        for pk in dict.fromkeys(obj.mcp_ids):
            mcp = await ai_buddy_mcp_dao.get(db, pk, user_id)
            if mcp is None:
                raise errors.RequestError(msg='MCP 不存在')
            mcp_ids.append(mcp.id)
        provider_id = obj.provider_id
        model_id = (obj.model_id or '').strip() or None
        if (provider_id is None) != (model_id is None):
            raise errors.RequestError(msg='覆盖模型需要同时填写供应商和模型')
        return obj.model_copy(
            update={
                'name': name,
                'conversation_id': conversation_id,
                'trigger': trigger,
                'prompt': prompt,
                'mcp_ids': mcp_ids,
                'provider_id': provider_id,
                'model_id': model_id,
            }
        )

    @staticmethod
    async def _ensure_quota(*, db: AsyncSession, user_id: int) -> None:
        """
        校验启用中的定时任务未达到上限

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        crons = await ai_buddy_cron_dao.get_all(db, user_id)
        if sum(1 for cron in crons if cron.status == StatusType.enable) >= CRON_USER_MAX_ENABLED:
            raise errors.RequestError(
                msg=f'启用中的定时任务最多 {CRON_USER_MAX_ENABLED} 个，请先删除或停用不需要的任务'
            )

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyCron]:
        """
        获取当前用户所有定时任务

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await ai_buddy_cron_dao.get_all(db, user_id)

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int) -> AIBuddyCron:
        """
        获取定时任务详情

        :param db: 数据库会话
        :param pk: 任务 ID
        :param user_id: 用户 ID
        :return:
        """
        cron = await ai_buddy_cron_dao.get(db, pk)
        if cron is None or cron.user_id != user_id:
            raise errors.NotFoundError(msg='定时任务不存在')
        return cron

    @staticmethod
    def _validate_trigger(trigger: str) -> None:
        """
        校验触发器的最小间隔和一次性任务的执行时间

        :param trigger: 规范化后的触发器
        :return:
        """
        kind, value = parse_trigger(trigger)
        if kind == 'interval' and int(value) < CRON_MIN_INTERVAL_SECONDS:
            raise errors.RequestError(msg=f'循环间隔不能小于 {CRON_MIN_INTERVAL_SECONDS} 秒')
        if kind == 'date' and parse_date_trigger(value) <= timezone.now():
            raise errors.RequestError(msg='一次性任务的执行时间必须晚于当前时间')

    async def create(self, *, db: AsyncSession, obj: CreateAIBuddyCronParam, user_id: int) -> AIBuddyCron:
        """
        创建定时任务

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        obj = await self._normalize(db=db, obj=obj, user_id=user_id, fallback=obj.conversation_id.strip())
        self._validate_trigger(obj.trigger)
        await self._ensure_quota(db=db, user_id=user_id)
        if await ai_buddy_cron_dao.get_by_name(db, user_id, obj.name):
            raise errors.ConflictError(msg='任务名称已存在')
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=obj.conversation_id,
            user_id=user_id,
        )
        return await ai_buddy_cron_dao.create(db, obj, user_id)

    async def update(self, *, db: AsyncSession, pk: int, obj: UpdateAIBuddyCronParam, user_id: int) -> int:
        """
        更新定时任务

        :param db: 数据库会话
        :param pk: 任务 ID
        :param obj: 更新参数
        :param user_id: 用户 ID
        :return:
        """
        cron = await self.get(db=db, pk=pk, user_id=user_id)
        obj = await self._normalize(db=db, obj=obj, user_id=user_id, fallback=str(pk))
        trigger_changed = obj.trigger != cron.trigger
        if trigger_changed:
            self._validate_trigger(obj.trigger)
        existed = await ai_buddy_cron_dao.get_by_name(db, user_id, obj.name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='任务名称已存在')
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=obj.conversation_id,
            user_id=user_id,
        )
        # 启停只能走 set_enabled，才会校验配额和一次性任务是否已执行完毕
        fields = obj.model_dump(exclude={'status'}, exclude_unset=True)
        if trigger_changed:
            fields['last_run_time'] = None
        return await ai_buddy_cron_dao.update(db, pk, fields)

    async def set_enabled(self, *, db: AsyncSession, pk: int, user_id: int, enabled: bool) -> AIBuddyCron:
        """
        启用或停用定时任务，已执行完毕的一次性任务不能再次启用

        :param db: 数据库会话
        :param pk: 任务 ID
        :param user_id: 用户 ID
        :param enabled: 是否启用
        :return:
        """
        cron = await self.get(db=db, pk=pk, user_id=user_id)
        if enabled and cron.status != StatusType.enable:
            if next_run_time(cron.trigger, last_run_time=cron.last_run_time, created_time=cron.created_time) is None:
                raise errors.RequestError(msg='一次性任务已执行完毕，不能再次启用，请重新创建')
            await self._ensure_quota(db=db, user_id=user_id)
        await ai_buddy_cron_dao.update_status(db, pk, StatusType.enable if enabled else StatusType.disable)
        return cron

    async def delete(self, *, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除定时任务

        :param db: 数据库会话
        :param pk: 任务 ID
        :param user_id: 用户 ID
        :return:
        """
        cron = await self.get(db=db, pk=pk, user_id=user_id)
        return await ai_buddy_cron_dao.delete(db, pk, cron.user_id)


ai_buddy_cron_service: AIBuddyCronService = AIBuddyCronService()
