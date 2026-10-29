import asyncio
import json

from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.core.conf import settings
from backend.database.redis import redis_client
from backend.plugin.ai_buddy.schema.delegation import ControlAIBuddyDelegationParam
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service


class AIBuddyDelegationService:
    """通过 Redis 将子代理控制路由到本轮所属进程"""

    @staticmethod
    def key(*, conversation_id: str, run_id: str) -> str:
        """
        生成与运行绑定的子任务缓存键

        :param conversation_id: 对话 ID
        :param run_id: 运行 ID
        :return:
        """
        return f'{settings.PLUGIN_REDIS_PREFIX}:ai_buddy:delegation:{conversation_id}:{run_id}'

    async def get_list(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        run_id: str,
    ) -> dict[str, Any]:
        """
        只向对话所有者返回本轮任务状态

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param run_id: 运行 ID
        :return:
        """
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        raw = await redis_client.get(self.key(conversation_id=conversation_id, run_id=run_id))
        if raw is None:
            raise errors.NotFoundError(msg='本轮子代理任务已结束或不存在')
        return json.loads(raw)

    async def control(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        task_id: str,
        obj: ControlAIBuddyDelegationParam,
    ) -> None:
        """
        提交引导或停止操作并等待执行进程确认

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param task_id: 子任务 ID
        :param obj: 控制参数
        :return:
        """
        state = await self.get_list(db=db, conversation_id=conversation_id, user_id=user_id, run_id=obj.run_id)
        task = next((item for item in state['tasks'] if item['task_id'] == task_id), None)
        if not state['active'] or task is None or task['status'] != 'running':
            raise errors.ConflictError(msg='子代理已结束，无法继续引导或停止')
        key = self.key(conversation_id=conversation_id, run_id=obj.run_id)
        command_id = uuid4().hex
        command = {'id': command_id, 'task_id': task_id, 'action': obj.action, 'text': obj.text}
        await redis_client.rpush(f'{key}:commands', json.dumps(command, ensure_ascii=False))
        await redis_client.expire(f'{key}:commands', 30)
        async with asyncio.timeout(15):
            while True:
                result = await redis_client.getdel(f'{key}:ack:{command_id}')
                if result is not None:
                    if result not in ('ok', b'ok'):
                        raise errors.ConflictError(msg='子代理已结束，操作未应用')
                    return
                await asyncio.sleep(0.05)


ai_buddy_delegation_service = AIBuddyDelegationService()
