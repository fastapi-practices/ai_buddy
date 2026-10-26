from pydantic import Field

from backend.common.schema import SchemaBase


class AIBuddyCitationDetail(SchemaBase):
    """模型供应商返回的网页引用来源"""

    url: str = Field(description='引用原始网页 URL')
    title: str = Field(description='供应商返回的来源标题')
