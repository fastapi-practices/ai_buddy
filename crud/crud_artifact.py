from collections.abc import Sequence

from sqlalchemy import Select, select
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

    async def get_select(self, user_id: int, kind: AIBuddyArtifactKind | None = None) -> Select:
        """
        获取当前用户按类型筛选的产物查询表达式

        :param user_id: 用户 ID
        :param kind: 产物类型，空则查询所有类型
        :return:
        """
        filters: dict[str, object] = {'user_id': user_id, 'deleted': 0}
        if kind is not None:
            filters['kind'] = kind
        return await self.select_order('id', 'desc', **filters)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyArtifact]:
        """
        获取当前用户所有产物

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(db, 'id', 'desc', user_id=user_id, deleted=0)

    async def create(
        self,
        db: AsyncSession,
        user_id: int,
        obj: CreateAIBuddyArtifactParam | RegisterAIBuddyArtifactParam,
        storage_id: int | None = None,
    ) -> AIBuddyArtifact:
        """
        创建产物

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param obj: 创建产物参数
        :param storage_id: 对象存储 ID
        :return:
        """
        ins = self.model(
            user_id=user_id,
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

    async def get_with_objects(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyArtifact]:
        """
        获取当前用户已写入对象存储的记录，供历史数据补登记统一对象

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        stmt = select(self.model).where(
            self.model.user_id == user_id,
            self.model.deleted == 0,
            self.model.object_key.is_not(None),
            self.model.relative_path.is_(None),
        )
        return (await db.execute(stmt.order_by(self.model.id.asc()))).scalars().all()


ai_buddy_artifact_dao: CRUDAIBuddyArtifact = CRUDAIBuddyArtifact(AIBuddyArtifact)
