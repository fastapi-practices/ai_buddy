from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.ai_buddy.cron.task_type import require_cron_name, require_cron_prompt
from backend.plugin.ai_buddy.cron.trigger import normalize_trigger
from backend.plugin.ai_buddy.crud.crud_cron import ai_buddy_cron_dao
from backend.plugin.ai_buddy.crud.crud_mcp import ai_buddy_mcp_dao
from backend.plugin.ai_buddy.model.cron import AIBuddyCron
from backend.plugin.ai_buddy.schema.cron import CreateAIBuddyCronParam, UpdateAIBuddyCronParam
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service


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

    async def create(self, *, db: AsyncSession, obj: CreateAIBuddyCronParam, user_id: int) -> None:
        """
        创建定时任务

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        obj = await self._normalize(db=db, obj=obj, user_id=user_id, fallback=obj.conversation_id.strip())
        if await ai_buddy_cron_dao.get_by_name(db, user_id, obj.name):
            raise errors.ConflictError(msg='任务名称已存在')
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=obj.conversation_id,
            user_id=user_id,
        )
        await ai_buddy_cron_dao.create(db, obj, user_id)

    async def update(self, *, db: AsyncSession, pk: int, obj: UpdateAIBuddyCronParam, user_id: int) -> int:
        """
        更新定时任务

        :param db: 数据库会话
        :param pk: 任务 ID
        :param obj: 更新参数
        :param user_id: 用户 ID
        :return:
        """
        await self.get(db=db, pk=pk, user_id=user_id)
        obj = await self._normalize(db=db, obj=obj, user_id=user_id, fallback=str(pk))
        existed = await ai_buddy_cron_dao.get_by_name(db, user_id, obj.name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='任务名称已存在')
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=obj.conversation_id,
            user_id=user_id,
        )
        return await ai_buddy_cron_dao.update(db, pk, obj)

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

    async def run_now(self, *, db: AsyncSession, pk: int, user_id: int) -> None:
        """
        立即执行一次定时任务

        :param db: 数据库会话
        :param pk: 任务 ID
        :param user_id: 用户 ID
        :return:
        """
        await self.get(db=db, pk=pk, user_id=user_id)
        from backend.plugin.ai_buddy.cron.tasks import deliver_cron_prompt

        await deliver_cron_prompt(cron_id=pk)


ai_buddy_cron_service: AIBuddyCronService = AIBuddyCronService()
