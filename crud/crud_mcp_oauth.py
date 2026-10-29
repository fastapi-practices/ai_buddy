from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.mcp import AIBuddyMcp
from backend.plugin.ai_buddy.model.mcp_oauth import AIBuddyMcpOauth
from backend.plugin.ai_buddy.model.mcp_oauth_config import AIBuddyMcpOauthConfig


class CRUDAIBuddyMcpOauth(CRUDPlus[AIBuddyMcpOauth]):
    """AI MCP 用户 OAuth 授权令牌数据库操作类"""

    async def get(self, db: AsyncSession, user_id: int, mcp_id: int) -> AIBuddyMcpOauth | None:
        """
        查询当前用户的授权连接

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param mcp_id: MCP ID
        :return:
        """
        stmt = select(self.model).where(
            self.model.user_id == user_id, self.model.mcp_id == mcp_id, self.model.deleted == 0
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyMcpOauth) -> None:
        """
        创建用户授权连接

        :param db: 数据库会话
        :param obj: 连接对象
        :return:
        """
        db.add(obj)
        await db.flush()

    async def update(self, db: AsyncSession, user_id: int, mcp_id: int, generation: str, values: dict[str, Any]) -> int:
        """
        仅更新仍匹配配置版本的凭据，防止旧回调覆盖断开操作

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param mcp_id: MCP ID
        :param generation: 原始配置版本
        :param values: 新值
        :return:
        """
        result = await db.execute(
            update(self.model)
            .where(
                self.model.user_id == user_id,
                self.model.mcp_id == mcp_id,
                self.model.generation == generation,
                self.model.deleted == 0,
            )
            .values(**values)
        )
        return result.rowcount

    async def invalidate(self, db: AsyncSession, mcp_id: int, generation: str) -> int:
        """
        平台配置或 MCP 定义变更后使所有个人授权失效

        :param db: 数据库会话
        :param mcp_id: MCP ID
        :param generation: 新连接版本
        :return:
        """
        result = await db.execute(
            update(self.model)
            .where(self.model.mcp_id == mcp_id, self.model.deleted == 0)
            .values(generation=generation, enabled=False, tokens_ciphertext=None, expires_time=None)
        )
        return result.rowcount

    async def save_tokens(self, db: AsyncSession, row: AIBuddyMcpOauth, values: dict[str, Any]) -> int:
        """
        只为仍有效的 MCP、平台配置和个人连接写入令牌

        :param db: 数据库会话
        :param row: 原始连接版本
        :param values: 新令牌与到期时间
        :return:
        """
        config_exists = (
            select(AIBuddyMcpOauthConfig.id)
            .where(
                AIBuddyMcpOauthConfig.mcp_id == row.mcp_id,
                AIBuddyMcpOauthConfig.generation == row.config_generation,
                AIBuddyMcpOauthConfig.server_url == row.server_url,
                AIBuddyMcpOauthConfig.enabled.is_(True),
                AIBuddyMcpOauthConfig.deleted == 0,
            )
            .exists()
        )
        mcp_exists = (
            select(AIBuddyMcp.id)
            .where(
                AIBuddyMcp.id == row.mcp_id,
                AIBuddyMcp.url == row.server_url,
                AIBuddyMcp.type != 0,
                AIBuddyMcp.user_id == 0,
                AIBuddyMcp.deleted == 0,
            )
            .exists()
        )
        result = await db.execute(
            update(self.model)
            .where(
                self.model.user_id == row.user_id,
                self.model.mcp_id == row.mcp_id,
                self.model.generation == row.generation,
                self.model.config_generation == row.config_generation,
                self.model.enabled.is_(True),
                self.model.deleted == 0,
                config_exists,
                mcp_exists,
            )
            .values(**values)
        )
        return result.rowcount


ai_buddy_mcp_oauth_dao: CRUDAIBuddyMcpOauth = CRUDAIBuddyMcpOauth(AIBuddyMcpOauth)
