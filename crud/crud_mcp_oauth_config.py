from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.crud.helpers import orm_values
from backend.plugin.ai_buddy.model.mcp_oauth_config import AIBuddyMcpOauthConfig


class CRUDAIBuddyMcpOauthConfig(CRUDPlus[AIBuddyMcpOauthConfig]):
    """AI 内置 MCP 平台 OAuth 配置数据库操作类"""

    async def get(self, db: AsyncSession, mcp_id: int) -> AIBuddyMcpOauthConfig | None:
        """
        查询内置 MCP 的平台客户端配置

        :param db: 数据库会话
        :param mcp_id: MCP ID
        :return:
        """
        return await self.select_model_by_column(db, mcp_id=mcp_id, deleted=0)

    async def create(self, db: AsyncSession, obj: AIBuddyMcpOauthConfig) -> None:
        """
        创建平台客户端配置

        :param db: 数据库会话
        :param obj: 配置对象
        :return:
        """
        await self.bulk_create_models(db, [orm_values(obj)], flush=True)

    async def update(self, db: AsyncSession, mcp_id: int, generation: str, values: dict[str, Any]) -> int:
        """
        仅更新仍匹配版本的平台配置

        :param db: 数据库会话
        :param mcp_id: MCP ID
        :param generation: 原始配置版本
        :param values: 新值
        :return:
        """
        result = await db.execute(
            update(self.model)
            .where(
                self.model.mcp_id == mcp_id,
                self.model.generation == generation,
                self.model.deleted == 0,
            )
            .values(**values)
        )
        return result.rowcount

    async def disable(self, db: AsyncSession, mcp_id: int, generation: str) -> int:
        """
        MCP 定义变更后停用平台配置并轮换版本

        :param db: 数据库会话
        :param mcp_id: MCP ID
        :param generation: 新配置版本
        :return:
        """
        result = await db.execute(
            update(self.model)
            .where(self.model.mcp_id == mcp_id, self.model.deleted == 0)
            .values(enabled=False, generation=generation)
        )
        return result.rowcount


ai_buddy_mcp_oauth_config_dao: CRUDAIBuddyMcpOauthConfig = CRUDAIBuddyMcpOauthConfig(AIBuddyMcpOauthConfig)
