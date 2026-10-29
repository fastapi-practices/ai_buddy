from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.ai_buddy.crud.crud_assistant import ai_buddy_assistant_dao
from backend.plugin.ai_buddy.crud.crud_expert import ai_buddy_expert_dao
from backend.plugin.ai_buddy.crud.crud_knowledge_base import ai_buddy_knowledge_base_dao
from backend.plugin.ai_buddy.crud.crud_mcp import ai_buddy_mcp_dao
from backend.plugin.ai_buddy.crud.crud_skill import ai_buddy_skill_dao
from backend.plugin.ai_buddy.model.expert import SYSTEM_EXPERT_USER_ID, AIBuddyExpert
from backend.plugin.ai_buddy.schema.assistant import CreateAIBuddyAssistantParam
from backend.plugin.ai_buddy.schema.expert import (
    CreateAIBuddyExpertParam,
    GetAIBuddyExpertWithRelationDetail,
    UpdateAIBuddyExpertParam,
)
from backend.plugin.ai_buddy.schema.knowledge_base import GetAIBuddyKnowledgeBaseDetail
from backend.plugin.ai_buddy.schema.mcp import GetAIBuddyMcpDetail
from backend.plugin.ai_buddy.schema.skill import GetAIBuddySkillSearchDetail
from backend.plugin.ai_buddy.service.assistant_service import ai_buddy_assistant_service


class AIBuddyExpertService:
    """AI 专家模板服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyExpert]:
        """
        获取当前用户可用的所有专家模板

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await ai_buddy_expert_dao.get_all(db, user_id)

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False) -> AIBuddyExpert:
        """
        获取专家模板详情

        :param db: 数据库会话
        :param pk: 专家 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        if is_superuser:
            expert = await ai_buddy_expert_dao.get(db, pk)
        else:
            expert = await ai_buddy_expert_dao.get_by_id_and_user_id(db, pk, user_id)
        if not expert:
            raise errors.NotFoundError(msg='专家不存在')
        return expert

    async def get_with_relation(self, *, db: AsyncSession, pk: int, user_id: int) -> GetAIBuddyExpertWithRelationDetail:
        """
        获取专家模板详情及当前用户可见的关联数据

        :param db: 数据库会话
        :param pk: 专家 ID
        :param user_id: 用户 ID
        :return:
        """
        expert = await self.get(db=db, pk=pk, user_id=user_id)
        detail = GetAIBuddyExpertWithRelationDetail.model_validate(expert)
        if expert.mcp_ids:
            mcps = {item.id: item for item in await ai_buddy_mcp_dao.get_by_ids(db, expert.mcp_ids, user_id)}
            detail.mcps = [
                GetAIBuddyMcpDetail.model_validate(mcps[pk]) for pk in dict.fromkeys(expert.mcp_ids) if pk in mcps
            ]
        if expert.skill_ids:
            skills = {item.id: item for item in await ai_buddy_skill_dao.get_by_ids(db, expert.skill_ids, user_id)}
            detail.skills = [
                GetAIBuddySkillSearchDetail.model_validate(skills[pk])
                for pk in dict.fromkeys(expert.skill_ids)
                if pk in skills
            ]
        if expert.knowledge_ids:
            knowledge_bases = {
                item.id: item
                for item in await ai_buddy_knowledge_base_dao.get_by_ids(db, expert.knowledge_ids, user_id)
            }
            detail.knowledge_bases = [
                GetAIBuddyKnowledgeBaseDetail.model_validate(knowledge_bases[pk])
                for pk in dict.fromkeys(expert.knowledge_ids)
                if pk in knowledge_bases
            ]

        return detail

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        name: str | None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """
        获取专家模板列表

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 专家名称
        :param is_superuser: 是否为超级管理员
        :return:
        """
        expert_select = await ai_buddy_expert_dao.get_select(None if is_superuser else user_id, name)
        return await paging_data(db, expert_select)

    async def create(self, *, db: AsyncSession, obj: CreateAIBuddyExpertParam, user_id: int) -> None:
        """
        创建专家模板

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        obj = self._normalize(obj=obj)
        await self._validate_relations(db=db, owner_id=user_id, obj=obj)
        if await ai_buddy_expert_dao.get_by_name(db, user_id, obj.name):
            raise errors.ConflictError(msg='专家名称已存在')
        await ai_buddy_expert_dao.create(db, obj, user_id)

    async def update(
        self,
        *,
        db: AsyncSession,
        pk: int,
        obj: UpdateAIBuddyExpertParam,
        user_id: int,
        is_superuser: bool,
    ) -> int:
        """
        更新专家模板

        :param db: 数据库会话
        :param pk: 专家 ID
        :param obj: 更新参数
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        expert = await self.get(db=db, pk=pk, user_id=user_id, is_superuser=is_superuser)
        if expert.user_id == SYSTEM_EXPERT_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统专家模板不允许修改')
        obj = self._normalize(obj=obj)
        await self._validate_relations(db=db, owner_id=expert.user_id, obj=obj, expert=expert)
        existed = await ai_buddy_expert_dao.get_by_name(db, expert.user_id, obj.name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='专家名称已存在')
        return await ai_buddy_expert_dao.update(db, pk, obj)

    async def delete(self, *, db: AsyncSession, pk: int, user_id: int, is_superuser: bool) -> int:
        """
        删除专家模板

        :param db: 数据库会话
        :param pk: 专家 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        expert = await self.get(db=db, pk=pk, user_id=user_id, is_superuser=is_superuser)
        if expert.user_id == SYSTEM_EXPERT_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统专家模板不允许删除')
        return await ai_buddy_expert_dao.delete(db, pk, expert.user_id)

    async def apply_to_assistant(
        self,
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
        name: str | None,
    ) -> dict[str, Any]:
        """
        用专家模板创建助手，本轮 MCP / 技能 / 知识仍可自选

        :param db: 数据库会话
        :param pk: 专家 ID
        :param user_id: 用户 ID
        :param name: 助手名称，空则使用专家名称
        :return:
        """
        expert = await self.get(db=db, pk=pk, user_id=user_id)
        assistant_name = (name or '').strip() or expert.name
        await ai_buddy_assistant_service.create(
            db=db,
            obj=CreateAIBuddyAssistantParam(
                name=assistant_name,
                prompt=expert.prompt,
                description=expert.description,
                starters=list(expert.starters or []),
            ),
            user_id=user_id,
        )
        created = await ai_buddy_assistant_dao.get_by_name(db, user_id, assistant_name)
        await ai_buddy_expert_dao.increment_usage(db, pk)
        return {
            'assistant_id': None if created is None else created.id,
            'mcp_ids': list(expert.mcp_ids or []),
            'skill_ids': list(expert.skill_ids or []),
            'knowledge_ids': list(expert.knowledge_ids or []),
            'starters': list(expert.starters or []),
        }

    @staticmethod
    async def _validate_relations(
        *,
        db: AsyncSession,
        owner_id: int,
        obj: CreateAIBuddyExpertParam | UpdateAIBuddyExpertParam,
        expert: AIBuddyExpert | None = None,
    ) -> None:
        """
        校验新增的 MCP、技能和知识库对专家所有者可见，已有的历史引用不重复校验

        :param db: 数据库会话
        :param owner_id: 专家所有者 ID
        :param obj: 创建或更新参数
        :param expert: 更新前的专家
        :return:
        """
        checks = (
            ('MCP', obj.mcp_ids, expert.mcp_ids if expert else None, ai_buddy_mcp_dao.get_by_ids),
            ('技能', obj.skill_ids, expert.skill_ids if expert else None, ai_buddy_skill_dao.get_by_ids),
            (
                '知识库',
                obj.knowledge_ids,
                expert.knowledge_ids if expert else None,
                ai_buddy_knowledge_base_dao.get_by_ids,
            ),
        )
        for label, requested, existing, fetch in checks:
            added = [pk for pk in requested if pk not in set(existing or ())]
            if not added:
                continue
            visible = {item.id for item in await fetch(db, added, owner_id)}
            missing = [pk for pk in added if pk not in visible]
            if missing:
                raise errors.RequestError(msg=f'{label}不存在或不可用: {missing}')

    @staticmethod
    def _normalize(
        *, obj: CreateAIBuddyExpertParam | UpdateAIBuddyExpertParam
    ) -> CreateAIBuddyExpertParam | UpdateAIBuddyExpertParam:
        """
        规范化专家模板字段

        :param obj: 创建或更新参数
        :return:
        """
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='专家名称不能为空')
        prompt = obj.prompt.strip()
        if not prompt:
            raise errors.RequestError(msg='专家提示词不能为空')
        description = obj.description.strip() if obj.description else None
        starters = [item.strip() for item in obj.starters if item.strip()]
        return obj.model_copy(
            update={
                'name': name,
                'prompt': prompt,
                'description': description or None,
                'starters': starters,
                'mcp_ids': list(dict.fromkeys(obj.mcp_ids)),
                'skill_ids': list(dict.fromkeys(obj.skill_ids)),
                'knowledge_ids': list(dict.fromkeys(obj.knowledge_ids)),
            }
        )


ai_buddy_expert_service: AIBuddyExpertService = AIBuddyExpertService()
