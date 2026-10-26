from pydantic import Field

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.schema.object import GetAIBuddyObjectDetail


class StageAIBuddyAttachmentUrlParam(SchemaBase):
    """从远程地址暂存附件参数"""

    url: str = Field(min_length=1, max_length=2048, description='公网 http/https 文件地址')


class PromoteAIBuddyAttachmentParam(SchemaBase):
    """提升暂存附件参数"""

    conversation_id: str = Field(min_length=1, max_length=64, description='引用该附件的对话 ID')


class GetAIBuddyAttachmentDetail(SchemaBase):
    """暂存附件"""

    object: GetAIBuddyObjectDetail = Field(description='统一对象元数据，state 为 tombstoned 表示仍在暂存期')
    filename: str = Field(description='文件名')
    content_type: str = Field(description='媒体类型')
