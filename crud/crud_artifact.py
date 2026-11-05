from collections.abc import Sequence

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.enums import AIBuddyArtifactKind
from backend.plugin.ai_buddy.model import AIBuddyArtifact
from backend.plugin.ai_buddy.schema.artifact import (
    CreateAIBuddyArtifactParam,
    RegisterAIBuddyArtifactParam,
    UpdateAIBuddyArtifactParam,
)


class CRUDAIBuddyArtifact(CRUDPlus[AIBuddyArtifact]):
    """AI 产物数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyArtifact | None:
        """
        获取产物

        :param db: 数据库会话
        :param pk: 产物 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_select(
        self, user_id: int, kind: AIBuddyArtifactKind | None = None, conversation_id: str | None = None
    ) -> Select:
        """
        获取当前用户按类型筛选的产物查询表达式

        :param user_id: 用户 ID
        :param kind: 产物类型，空则查询所有类型
        :param conversation_id: 对话 ID，空则查询用户全部产物
        :return:
        """
        filters: dict[str, object] = {'user_id': user_id, 'deleted': 0}
        if kind is not None:
            filters['kind'] = kind
        if conversation_id is not None:
            filters['conversation_id'] = conversation_id
        return await self.select_order('id', 'desc', **filters)

    async def get_all(
        self, db: AsyncSession, user_id: int, conversation_id: str | None = None
    ) -> Sequence[AIBuddyArtifact]:
        """
        获取当前用户所有产物

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 对话 ID，空则查询用户全部产物
        :return:
        """
        filters: dict[str, object] = {'user_id': user_id, 'deleted': 0}
        if conversation_id is not None:
            filters['conversation_id'] = conversation_id
        return await self.select_models_order(db, 'id', 'desc', **filters)

    async def create(
        self,
        db: AsyncSession,
        user_id: int,
        obj: CreateAIBuddyArtifactParam | RegisterAIBuddyArtifactParam,
        storage_id: int | None = None,
        conversation_id: str | None = None,
    ) -> AIBuddyArtifact:
        """
        创建产物

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param obj: 创建产物参数
        :param storage_id: 对象存储 ID
        :param conversation_id: 来源对话 ID
        :return:
        """
        ins = self.model(
            user_id=user_id,
            conversation_id=conversation_id,
            title=obj.title,
            kind=obj.kind,
            storage_id=storage_id,
            storage_backend=obj.storage_backend,
            workspace_id=obj.workspace_id,
            relative_path=obj.relative_path,
            mime_type=obj.mime_type,
            size=obj.size,
            sha256=obj.sha256,
            state=obj.state,
        )
        db.add(ins)
        await db.flush()
        return ins

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyArtifactParam | dict) -> int:
        """
        更新产物

        :param db: 数据库会话
        :param pk: 产物 ID
        :param obj: 更新产物参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)


ai_buddy_artifact_dao: CRUDAIBuddyArtifact = CRUDAIBuddyArtifact(AIBuddyArtifact)
