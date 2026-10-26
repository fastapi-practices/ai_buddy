from pydantic import Field

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyWebSearchType


class GetAIBuddyWebSearchOptionDetail(SchemaBase):
    """联网搜索选项"""

    type: AIBuddyWebSearchType = Field(description='搜索类型')
    name: str = Field(description='搜索名称')
    status: StatusType = Field(description='整体状态')
    key_status: StatusType = Field(description='密钥配置状态')
