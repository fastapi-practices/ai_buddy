from pydantic import Field

from backend.common.schema import SchemaBase


class AIBuddyObjectBackfillParam(SchemaBase):
    """历史对象补登记参数"""

    dry_run: bool = Field(True, description='默认仅预览，设为 false 才会写入统一对象和引用')


class GetAIBuddyObjectBackfillDetail(SchemaBase):
    """历史对象补登记结果"""

    artifacts: int = Field(description='需要或已经补登记的产物数')
    knowledges: int = Field(description='需要或已经补登记的知识数')
    skills: int = Field(description='需要或已经补登记的技能数')
    storage_filled: int = Field(description='缺少 storage_id、已回填为默认存储的记录数')
    skipped: int = Field(description='已处于登记状态或无法补登记的记录数')
