from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.ai_buddy.crud.crud_permission import ai_buddy_permission_profile_dao, ai_buddy_permission_rule_dao
from backend.plugin.ai_buddy.enums import AIBuddyPermissionMatchKind, AIBuddyToolPolicy
from backend.plugin.ai_buddy.model.permission_profile import AIBuddyPermissionProfile
from backend.plugin.ai_buddy.schema.permission import (
    CopyAIBuddyPermissionProfileParam,
    CreateAIBuddyPermissionProfileParam,
    CreateAIBuddyPermissionRuleParam,
    GetAIBuddyPermissionProfileWithRulesDetail,
    GetAIBuddyPermissionRuleDetail,
    UpdateAIBuddyPermissionProfileParam,
)
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID
from backend.utils.timezone import timezone


class AIBuddyPermissionService:
    """AI 工具权限预设服务类"""

    @staticmethod
    def _normalize_code(*, code: str | None) -> str:
        """
        规范化预设编码，自定义预设未填写时自动生成

        :param code: 客户端编码
        :return:
        """
        value = (code or '').strip()
        return value or f'custom_{uuid4().hex[:8]}'

    @staticmethod
    def _normalize_rule(*, rule: CreateAIBuddyPermissionRuleParam) -> dict[str, Any]:
        """
        规范化并校验单条工具规则

        :param rule: 工具规则
        :return:
        """
        if rule.match_kind != AIBuddyPermissionMatchKind.any:
            raise errors.RequestError(msg='首版仅支持 any 规则')
        tool_name = rule.tool_name.strip()
        if not tool_name:
            raise errors.RequestError(msg='工具名不能为空')
        try:
            action = AIBuddyToolPolicy(str(rule.action).strip().lower())
        except ValueError as exc:
            raise errors.RequestError(msg='工具策略必须为 allow、ask 或 deny') from exc
        return {
            'tool_name': tool_name,
            'action': action.value,
            'match_kind': AIBuddyPermissionMatchKind.any.value,
            'match_value': '',
            'priority': rule.priority,
            'enabled': rule.enabled,
        }

    @classmethod
    def _normalize_rules(
        cls,
        *,
        rules: Sequence[CreateAIBuddyPermissionRuleParam],
    ) -> list[dict[str, Any]]:
        """
        规范化规则列表并拒绝规范化后的重复工具规则

        :param rules: 工具规则列表
        :return:
        """
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for rule in rules:
            item = cls._normalize_rule(rule=rule)
            tool_name = item['tool_name']
            if tool_name in seen:
                raise errors.RequestError(msg=f'工具 {tool_name} 的规则重复')
            seen.add(tool_name)
            normalized.append(item)
        return normalized

    @staticmethod
    async def _ensure_code_unique(
        *,
        db: AsyncSession,
        user_id: int,
        code: str,
        exclude_id: int | None = None,
    ) -> None:
        """
        校验同一归属下的预设编码唯一

        :param db: 数据库会话
        :param user_id: 归属用户 ID
        :param code: 预设编码
        :param exclude_id: 更新时排除的预设 ID
        :return:
        """
        existed = await ai_buddy_permission_profile_dao.get_by_code(db, user_id, code)
        if existed is not None and existed.id != exclude_id:
            raise errors.ConflictError(msg='权限预设编码已存在')

    @staticmethod
    async def _replace_rules(
        *,
        db: AsyncSession,
        profile_id: int,
        rules: Sequence[CreateAIBuddyPermissionRuleParam],
    ) -> None:
        """
        完整替换预设规则

        :param db: 数据库会话
        :param profile_id: 预设 ID
        :param rules: 工具规则列表
        :return:
        """
        normalized = AIBuddyPermissionService._normalize_rules(rules=rules)
        await ai_buddy_permission_rule_dao.delete_by_profile(db, profile_id)
        if not normalized:
            return
        created_time = timezone.now()
        await ai_buddy_permission_rule_dao.create_many(
            db,
            [{**rule, 'profile_id': profile_id, 'created_time': created_time} for rule in normalized],
        )

    @staticmethod
    async def _get_visible(
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
        is_superuser: bool,
    ) -> AIBuddyPermissionProfile:
        """
        获取当前用户可见的权限预设

        :param db: 数据库会话
        :param pk: 预设 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        profile = await ai_buddy_permission_profile_dao.get_visible(
            db,
            pk,
            user_id=user_id,
            is_superuser=is_superuser,
        )
        if profile is None:
            raise errors.NotFoundError(msg='权限预设不存在')
        return profile

    @staticmethod
    async def _get_manageable(
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
        is_superuser: bool,
    ) -> AIBuddyPermissionProfile:
        """
        获取当前用户可修改或删除的权限预设

        :param db: 数据库会话
        :param pk: 预设 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        profile = await AIBuddyPermissionService._get_visible(
            db=db,
            pk=pk,
            user_id=user_id,
            is_superuser=is_superuser,
        )
        if profile.user_id == SYSTEM_OWNER_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统内置权限预设不允许修改或删除')
        return profile

    @staticmethod
    async def get_all(
        *,
        db: AsyncSession,
        user_id: int,
        status: StatusType | None = None,
        builtin: bool | None = None,
        is_superuser: bool = False,
    ) -> Sequence[AIBuddyPermissionProfile]:
        """
        获取当前用户可见的全部权限预设

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param status: 状态
        :param builtin: 是否系统内置
        :param is_superuser: 是否为超级管理员
        :return:
        """
        return await ai_buddy_permission_profile_dao.get_all(
            db,
            user_id=None if is_superuser else user_id,
            status=status,
            builtin=builtin,
        )

    @staticmethod
    async def get(
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
        is_superuser: bool = False,
    ) -> GetAIBuddyPermissionProfileWithRulesDetail:
        """
        获取权限预设及全部规则详情

        :param db: 数据库会话
        :param pk: 预设 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        profile = await AIBuddyPermissionService._get_visible(
            db=db,
            pk=pk,
            user_id=user_id,
            is_superuser=is_superuser,
        )
        rules = await ai_buddy_permission_rule_dao.get_by_profile(db, pk)
        detail = GetAIBuddyPermissionProfileWithRulesDetail.model_validate(profile)
        return detail.model_copy(
            update={'rules': [GetAIBuddyPermissionRuleDetail.model_validate(rule) for rule in rules]}
        )

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        name: str | None,
        status: StatusType | None,
        builtin: bool | None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """
        分页获取权限预设

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 预设名称
        :param status: 状态
        :param builtin: 是否系统内置
        :param is_superuser: 是否为超级管理员
        :return:
        """
        profile_select = await ai_buddy_permission_profile_dao.get_select(
            user_id=None if is_superuser else user_id,
            name=name,
            status=status,
            builtin=builtin,
        )
        return await paging_data(db, profile_select)

    @staticmethod
    async def create(
        *,
        db: AsyncSession,
        obj: CreateAIBuddyPermissionProfileParam,
        user_id: int,
        is_superuser: bool = False,
    ) -> AIBuddyPermissionProfile:
        """
        创建权限预设

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 归属用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        builtin = user_id == SYSTEM_OWNER_USER_ID
        if builtin and not is_superuser:
            raise errors.ForbiddenError(msg='只有超级管理员可以创建系统权限预设')
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='权限预设名称不能为空')
        code = AIBuddyPermissionService._normalize_code(code=obj.code)
        await AIBuddyPermissionService._ensure_code_unique(db=db, user_id=user_id, code=code)
        description = obj.description.strip() if obj.description else None
        profile = await ai_buddy_permission_profile_dao.create(
            db,
            user_id=user_id,
            code=code,
            name=name,
            description=description or None,
            builtin=builtin,
            status=obj.status,
            sort=obj.sort,
        )
        await AIBuddyPermissionService._replace_rules(db=db, profile_id=profile.id, rules=obj.rules)
        return profile

    @staticmethod
    async def update(
        *,
        db: AsyncSession,
        pk: int,
        obj: UpdateAIBuddyPermissionProfileParam,
        user_id: int,
        is_superuser: bool = False,
    ) -> int:
        """
        更新权限预设，传入规则列表时完整替换规则

        :param db: 数据库会话
        :param pk: 预设 ID
        :param obj: 更新参数
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        profile = await AIBuddyPermissionService._get_manageable(
            db=db,
            pk=pk,
            user_id=user_id,
            is_superuser=is_superuser,
        )
        if obj.rules is not None:
            AIBuddyPermissionService._normalize_rules(rules=obj.rules)
        values: dict[str, Any] = {}
        if obj.code is not None:
            code = AIBuddyPermissionService._normalize_code(code=obj.code)
            await AIBuddyPermissionService._ensure_code_unique(
                db=db,
                user_id=profile.user_id,
                code=code,
                exclude_id=pk,
            )
            values['code'] = code
        if obj.name is not None:
            name = obj.name.strip()
            if not name:
                raise errors.RequestError(msg='权限预设名称不能为空')
            values['name'] = name
        if 'description' in obj.model_fields_set:
            values['description'] = obj.description.strip() if obj.description else None
        if obj.status is not None:
            values['status'] = obj.status
        if obj.sort is not None:
            values['sort'] = obj.sort
        count = await ai_buddy_permission_profile_dao.update(db, pk, values) if values else 1
        if count > 0 and obj.rules is not None:
            await AIBuddyPermissionService._replace_rules(db=db, profile_id=pk, rules=obj.rules)
        return count

    @staticmethod
    async def delete(
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
        is_superuser: bool = False,
    ) -> int:
        """
        删除权限预设及其规则

        :param db: 数据库会话
        :param pk: 预设 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        profile = await AIBuddyPermissionService._get_manageable(
            db=db,
            pk=pk,
            user_id=user_id,
            is_superuser=is_superuser,
        )
        await ai_buddy_permission_rule_dao.delete_by_profile(db, pk)
        return await ai_buddy_permission_profile_dao.delete(db, pk, profile.user_id)

    @staticmethod
    async def copy(
        *,
        db: AsyncSession,
        pk: int,
        obj: CopyAIBuddyPermissionProfileParam,
        user_id: int,
        is_superuser: bool = False,
    ) -> AIBuddyPermissionProfile:
        """
        复制可见预设为当前用户的自定义预设

        :param db: 数据库会话
        :param pk: 源预设 ID
        :param obj: 复制参数
        :param user_id: 目标用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        source = await AIBuddyPermissionService._get_visible(
            db=db,
            pk=pk,
            user_id=user_id,
            is_superuser=is_superuser,
        )
        code = AIBuddyPermissionService._normalize_code(code=obj.code)
        await AIBuddyPermissionService._ensure_code_unique(db=db, user_id=user_id, code=code)
        name = obj.name.strip() if obj.name else f'{source.name}（副本）'
        if not name:
            raise errors.RequestError(msg='权限预设名称不能为空')
        description = (
            (obj.description.strip() if obj.description else None)
            if 'description' in obj.model_fields_set
            else source.description
        )
        profile = await ai_buddy_permission_profile_dao.create(
            db,
            user_id=user_id,
            code=code,
            name=name,
            description=description or None,
            builtin=False,
            status=source.status,
            sort=source.sort,
        )
        rules = await ai_buddy_permission_rule_dao.get_by_profile(db, pk)
        created_time = timezone.now()
        await ai_buddy_permission_rule_dao.create_many(
            db,
            [
                {
                    'profile_id': profile.id,
                    'tool_name': rule.tool_name,
                    'action': rule.action,
                    'match_kind': rule.match_kind,
                    'match_value': rule.match_value,
                    'priority': rule.priority,
                    'enabled': rule.enabled,
                    'created_time': created_time,
                }
                for rule in rules
            ],
        )
        return profile

    @staticmethod
    async def resolve_runtime_policies(
        *,
        db: AsyncSession,
        profile_id: int,
        user_id: int,
        is_superuser: bool = False,
    ) -> dict[str, AIBuddyToolPolicy]:
        """
        解析服务端预设计算本轮工具策略，未知工具默认询问

        :param db: 数据库会话
        :param profile_id: 权限预设 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        profile = await AIBuddyPermissionService._get_visible(
            db=db,
            pk=profile_id,
            user_id=user_id,
            is_superuser=is_superuser,
        )
        if profile.status != StatusType.enable:
            raise errors.RequestError(msg='当前权限预设已停用')
        rules = await ai_buddy_permission_rule_dao.get_enabled_any_by_profile(db, profile_id)
        policies: dict[str, AIBuddyToolPolicy] = {}
        for rule in rules:
            if rule.tool_name in policies:
                continue
            try:
                policies[rule.tool_name] = AIBuddyToolPolicy(str(rule.action).strip().lower())
            except ValueError:
                continue
        policies.setdefault('*', AIBuddyToolPolicy.ask)
        return policies


ai_buddy_permission_service: AIBuddyPermissionService = AIBuddyPermissionService()
