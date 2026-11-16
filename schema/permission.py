from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyPermissionMatchKind, AIBuddyToolPolicy

_PERMISSION_CODE_PATTERN = r'^[a-z][a-z0-9_-]{1,63}$'
_TOOL_NAME_PATTERN = r'^[A-Za-z0-9_.:*+-]+$'


class AIBuddyPermissionRuleSchemaBase(SchemaBase):
    """AI 工具权限规则基础模型"""

    tool_name: str = Field(pattern=_TOOL_NAME_PATTERN, description='工具名，* 表示默认规则')
    action: AIBuddyToolPolicy = Field(description='工具策略：allow / ask / deny')
    match_kind: AIBuddyPermissionMatchKind = Field(
        default=AIBuddyPermissionMatchKind.any,
        description='匹配方式，首版仅 any 参与运行时求值',
    )
    match_value: str = Field(default='', max_length=512, description='匹配值，首版 any 必须为空')
    priority: int = Field(default=0, description='同工具规则优先级')
    enabled: bool = Field(default=True, description='是否启用')

    @field_validator('tool_name', mode='before')
    @classmethod
    def normalize_tool_name(cls, value: str) -> str:
        """
        规范化工具名

        :param value: 工具名
        :return:
        """
        return value.strip()

    @field_validator('match_value', mode='before')
    @classmethod
    def normalize_match_value(cls, value: str | None) -> str:
        """
        规范化匹配值

        :param value: 匹配值
        :return:
        """
        return value.strip() if value else ''


class CreateAIBuddyPermissionRuleParam(AIBuddyPermissionRuleSchemaBase):
    """创建 AI 工具权限规则参数"""


class CreateAIBuddyPermissionProfileParam(SchemaBase):
    """创建 AI 工具权限预设参数"""

    code: str | None = Field(
        default=None,
        pattern=_PERMISSION_CODE_PATTERN,
        description='预设编码，自定义预设为空时由服务端生成',
    )
    name: str = Field(min_length=1, max_length=128, description='预设名称')
    description: str | None = Field(default=None, max_length=512, description='预设说明')
    status: StatusType = Field(default=StatusType.enable, description='状态')
    sort: int = Field(default=0, description='排序')
    rules: list[CreateAIBuddyPermissionRuleParam] = Field(default_factory=list, description='工具规则列表')


class UpdateAIBuddyPermissionProfileParam(SchemaBase):
    """更新 AI 工具权限预设参数"""

    code: str | None = Field(default=None, pattern=_PERMISSION_CODE_PATTERN, description='预设编码')
    name: str | None = Field(default=None, min_length=1, max_length=128, description='预设名称')
    description: str | None = Field(default=None, max_length=512, description='预设说明')
    status: StatusType | None = Field(default=None, description='状态')
    sort: int | None = Field(default=None, description='排序')
    rules: Annotated[
        list[CreateAIBuddyPermissionRuleParam] | None,
        Field(description='完整替换规则，空列表表示清空，空值表示不修改'),
    ] = None


class CopyAIBuddyPermissionProfileParam(SchemaBase):
    """复制 AI 工具权限预设参数"""

    code: str | None = Field(default=None, pattern=_PERMISSION_CODE_PATTERN, description='新预设编码')
    name: str | None = Field(default=None, min_length=1, max_length=128, description='新预设名称')
    description: str | None = Field(default=None, max_length=512, description='新预设说明')


class AIBuddyPermissionProfileQueryParam(SchemaBase):
    """AI 工具权限预设查询参数"""

    name: str | None = Field(default=None, description='预设名称')
    status: StatusType | None = Field(default=None, description='状态')
    builtin: bool | None = Field(default=None, description='是否系统内置')


class GetAIBuddyPermissionRuleDetail(AIBuddyPermissionRuleSchemaBase):
    """AI 工具权限规则详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='规则 ID')
    profile_id: int = Field(description='权限预设 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(default=None, description='更新时间')


class GetAIBuddyPermissionProfileDetail(SchemaBase):
    """AI 工具权限预设详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='预设 ID')
    user_id: int = Field(description='用户 ID，0 表示系统预设')
    code: str = Field(description='预设编码')
    name: str = Field(description='预设名称')
    description: str | None = Field(default=None, description='预设说明')
    builtin: bool = Field(description='是否系统内置')
    status: StatusType = Field(description='状态')
    sort: int = Field(description='排序')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(default=None, description='更新时间')


class GetAIBuddyPermissionProfileWithRulesDetail(GetAIBuddyPermissionProfileDetail):
    """AI 工具权限预设及规则详情"""

    rules: list[GetAIBuddyPermissionRuleDetail] = Field(default_factory=list, description='工具规则列表')
