from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.ai_buddy.crud.crud_artifact import ai_buddy_artifact_dao
from backend.plugin.ai_buddy.crud.crud_knowledge import ai_buddy_knowledge_dao
from backend.plugin.ai_buddy.crud.crud_object import ai_buddy_object_dao
from backend.plugin.ai_buddy.crud.crud_object_ref import ai_buddy_object_ref_dao
from backend.plugin.ai_buddy.crud.crud_skill import ai_buddy_skill_dao
from backend.plugin.ai_buddy.enums import AIBuddyArtifactState, AIBuddyObjectKind, AIBuddyObjectLocation
from backend.plugin.ai_buddy.schema.object_backfill import GetAIBuddyObjectBackfillDetail
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service
from backend.plugin.s3.utils.text_store import require_storage


class AIBuddyObjectBackfillService:
    """历史对象补登记服务类，让旧产物、知识和技能进入统一对象注册表，操作可重复执行"""

    async def run(self, *, db: AsyncSession, user_id: int, dry_run: bool) -> GetAIBuddyObjectBackfillDetail:
        """
        为当前用户的历史记录补登记统一对象与引用，缺少 storage_id 的记录回填为默认存储

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param dry_run: 仅预览，不写入
        :return:
        """
        result = {'artifacts': 0, 'knowledges': 0, 'skills': 0, 'storage_filled': 0, 'skipped': 0}
        default_storage = await require_storage(db=db)
        targets = (
            (
                'artifacts',
                'artifact',
                AIBuddyObjectKind.artifact,
                await ai_buddy_artifact_dao.get_with_objects(db, user_id),
            ),
            (
                'knowledges',
                'knowledge',
                AIBuddyObjectKind.knowledge,
                await ai_buddy_knowledge_dao.get_with_objects(db, user_id),
            ),
            ('skills', 'skill', AIBuddyObjectKind.skill, await ai_buddy_skill_dao.get_with_objects(db, user_id)),
        )
        for field, owner_type, kind, rows in targets:
            for row in rows:
                if getattr(row, 'state', None) == AIBuddyArtifactState.deleted:
                    result['skipped'] += 1
                    continue
                object_key = f'{row.object_key.rstrip("/")}/' if kind == AIBuddyObjectKind.skill else row.object_key
                storage_id = row.storage_id or default_storage.id
                existing = await ai_buddy_object_dao.get_by_key(
                    db, AIBuddyObjectLocation.s3.value, storage_id, object_key
                )
                if (
                    existing is not None
                    and await ai_buddy_object_ref_dao.get_by_owner(db, existing.id, owner_type, str(row.id)) is not None
                    and row.storage_id
                ):
                    result['skipped'] += 1
                    continue
                result[field] += 1
                if row.storage_id is None:
                    result['storage_filled'] += 1
                if dry_run:
                    continue
                row.storage_id = storage_id
                stored = await ai_buddy_object_service.register(
                    db=db,
                    user_id=user_id,
                    kind=kind,
                    location=AIBuddyObjectLocation.s3,
                    object_key=object_key,
                    storage_id=storage_id,
                )
                await ai_buddy_object_service.add_reference(
                    db=db, obj=stored, owner_type=owner_type, owner_id=str(row.id), actor_id=user_id
                )
        return GetAIBuddyObjectBackfillDetail(**result)


ai_buddy_object_backfill_service: AIBuddyObjectBackfillService = AIBuddyObjectBackfillService()
