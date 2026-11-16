from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.crud.helpers import orm_values
from backend.plugin.ai_buddy.enums import AIBuddyPermissionMatchKind
from backend.plugin.ai_buddy.model.permission_profile import AIBuddyPermissionProfile
from backend.plugin.ai_buddy.model.permission_rule import AIBuddyPermissionRule
from backend.plugin.ai_buddy.utils.ownership import visible_owner_ids
from backend.utils.timezone import timezone


class CRUDAIBuddyPermissionProfile(CRUDPlus[AIBuddyPermissionProfile]):
    """AI 工具权限预设数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyPermissionProfile | None:
        """
        获取权限预设

        :param db: 数据库会话
        :param pk: 预设 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_visible(
        self,
        db: AsyncSession,
        pk: int,
        *,
        user_id: int,
        is_superuser: bool = False,
    ) -> AIBuddyPermissionProfile | None:
        """
        获取当前用户可见的权限预设

        :param db: 数据库会话
        :param pk: 预设 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        profile = await self.get(db, pk)
        if profile is None:
            return None
        if is_superuser or profile.user_id in visible_owner_ids(user_id):
            return profile
        return None

    async def get_by_code(self, db: AsyncSession, user_id: int, code: str) -> AIBuddyPermissionProfile | None:
        """
        通过归属和编码获取权限预设

        :param db: 数据库会话
        :param user_id: 归属用户 ID
        :param code: 预设编码
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, code=code, deleted=0)

    async def get_select(
        self,
        *,
        user_id: int | None,
        name: str | None,
        status: int | None,
        builtin: bool | None,
    ) -> Select:
        """
        获取权限预设列表查询表达式

        :param user_id: 当前用户 ID，空则不限制归属
        :param name: 预设名称
        :param status: 状态
        :param builtin: 是否系统内置
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if user_id is not None:
            filters['user_id__in'] = visible_owner_ids(user_id)
        if name is not None:
            filters['name__ilike'] = f'%{name}%'
        if status is not None:
            filters['status'] = status
        if builtin is not None:
            filters['builtin'] = builtin
        return await self.select_order(['user_id', 'sort', 'id'], ['asc', 'desc', 'asc'], **filters)

    async def get_all(
        self,
        db: AsyncSession,
        *,
        user_id: int | None,
        status: int | None = None,
        builtin: bool | None = None,
    ) -> Sequence[AIBuddyPermissionProfile]:
        """
        获取权限预设列表

        :param db: 数据库会话
        :param user_id: 当前用户 ID，空则不限制归属
        :param status: 状态
        :param builtin: 是否系统内置
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if user_id is not None:
            filters['user_id__in'] = visible_owner_ids(user_id)
        if status is not None:
            filters['status'] = status
        if builtin is not None:
            filters['builtin'] = builtin
        return await self.select_models_order(db, ['user_id', 'sort', 'id'], ['asc', 'desc', 'asc'], **filters)

    async def create(self, db: AsyncSession, **values: Any) -> AIBuddyPermissionProfile:
        """
        创建权限预设

        :param db: 数据库会话
        :param values: 预设字段
        :return:
        """
        profile = AIBuddyPermissionProfile(**values)
        rows = await self.bulk_create_models(db, [orm_values(profile)], flush=True)
        return rows[0]

    async def update(self, db: AsyncSession, pk: int, values: dict[str, Any]) -> int:
        """
        更新权限预设

        :param db: 数据库会话
        :param pk: 预设 ID
        :param values: 待更新字段
        :return:
        """
        return await self.update_model_by_column(db, values, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        逻辑删除权限预设

        :param db: 数据库会话
        :param pk: 预设 ID
        :param user_id: 归属用户 ID
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


class CRUDAIBuddyPermissionRule(CRUDPlus[AIBuddyPermissionRule]):
    """AI 工具权限规则数据库操作类"""

    async def get_by_profile(self, db: AsyncSession, profile_id: int) -> Sequence[AIBuddyPermissionRule]:
        """
        获取预设的全部规则

        :param db: 数据库会话
        :param profile_id: 预设 ID
        :return:
        """
        return await self.select_models_order(db, ['priority', 'id'], ['desc', 'asc'], profile_id=profile_id, deleted=0)

    async def get_enabled_any_by_profile(
        self,
        db: AsyncSession,
        profile_id: int,
    ) -> Sequence[AIBuddyPermissionRule]:
        """
        获取预设中参与运行时求值的启用规则

        :param db: 数据库会话
        :param profile_id: 预设 ID
        :return:
        """
        return await self.select_models_order(
            db,
            ['priority', 'id'],
            ['desc', 'asc'],
            profile_id=profile_id,
            match_kind=AIBuddyPermissionMatchKind.any,
            enabled=True,
            deleted=0,
        )

    async def create_many(self, db: AsyncSession, rules: list[dict[str, Any]]) -> None:
        """
        批量创建权限规则

        :param db: 数据库会话
        :param rules: 规则字段列表
        :return:
        """
        if not rules:
            return
        await self.bulk_create_models(db, rules, flush=True)

    async def delete_by_profile(self, db: AsyncSession, profile_id: int) -> int:
        """
        逻辑删除预设下的全部规则

        :param db: 数据库会话
        :param profile_id: 预设 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            allow_multiple=True,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            profile_id=profile_id,
            deleted=0,
        )


ai_buddy_permission_profile_dao: CRUDAIBuddyPermissionProfile = CRUDAIBuddyPermissionProfile(AIBuddyPermissionProfile)
ai_buddy_permission_rule_dao: CRUDAIBuddyPermissionRule = CRUDAIBuddyPermissionRule(AIBuddyPermissionRule)
