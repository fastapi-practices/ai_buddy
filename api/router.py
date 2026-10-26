from fastapi import APIRouter

from backend.core.conf import settings
from backend.plugin.ai_buddy.api.v1.acp import router as acp_router
from backend.plugin.ai_buddy.api.v1.approval_audit import router as approval_audit_router
from backend.plugin.ai_buddy.api.v1.artifact import router as artifact_router
from backend.plugin.ai_buddy.api.v1.assistant import router as assistant_router
from backend.plugin.ai_buddy.api.v1.attachment import router as attachment_router
from backend.plugin.ai_buddy.api.v1.channel import router as channel_router
from backend.plugin.ai_buddy.api.v1.chat import router as chat_router
from backend.plugin.ai_buddy.api.v1.conversation import router as conversation_router
from backend.plugin.ai_buddy.api.v1.conversation_transfer import router as conversation_transfer_router
from backend.plugin.ai_buddy.api.v1.cron import router as cron_router
from backend.plugin.ai_buddy.api.v1.default_model import router as default_model_router
from backend.plugin.ai_buddy.api.v1.execution import router as execution_router
from backend.plugin.ai_buddy.api.v1.expert import router as expert_router
from backend.plugin.ai_buddy.api.v1.image import router as image_router
from backend.plugin.ai_buddy.api.v1.knowledge import router as knowledge_router
from backend.plugin.ai_buddy.api.v1.knowledge_base import router as knowledge_base_router
from backend.plugin.ai_buddy.api.v1.mcp import router as mcp_router
from backend.plugin.ai_buddy.api.v1.mcp_app import router as mcp_app_router
from backend.plugin.ai_buddy.api.v1.mcp_oauth import router as mcp_oauth_router
from backend.plugin.ai_buddy.api.v1.memory import router as memory_router
from backend.plugin.ai_buddy.api.v1.message import router as message_router
from backend.plugin.ai_buddy.api.v1.model import router as model_router
from backend.plugin.ai_buddy.api.v1.model_option import router as model_option_router
from backend.plugin.ai_buddy.api.v1.object import router as object_router
from backend.plugin.ai_buddy.api.v1.project import router as project_router
from backend.plugin.ai_buddy.api.v1.provider import router as provider_router
from backend.plugin.ai_buddy.api.v1.quick_phrase import router as quick_phrase_router
from backend.plugin.ai_buddy.api.v1.skill import router as skill_router
from backend.plugin.ai_buddy.api.v1.slash import router as slash_router
from backend.plugin.ai_buddy.api.v1.subagent import router as subagent_router
from backend.plugin.ai_buddy.api.v1.sync import router as sync_router
from backend.plugin.ai_buddy.api.v1.web_search import router as web_search_router
from backend.plugin.ai_buddy.api.v1.workspace import router as workspace_router

v1 = APIRouter(prefix=settings.FASTAPI_API_V1_PATH)

v1.include_router(chat_router, prefix='/chat', tags=['AI 对话'])
v1.include_router(acp_router, prefix='/acp', tags=['AI ACP 管理'])
v1.include_router(execution_router, prefix='/execution', tags=['AI 执行后端'])
v1.include_router(image_router, prefix='/images', tags=['AI 生图'])
v1.include_router(model_option_router, prefix='/model-options', tags=['AI 模型管理'])
v1.include_router(web_search_router, prefix='/web-search-options', tags=['AI 联网搜索'])
v1.include_router(default_model_router, prefix='/default-models', tags=['AI 默认模型管理'])
v1.include_router(conversation_router, prefix='/conversations', tags=['AI 对话管理'])
v1.include_router(message_router, prefix='/conversations', tags=['AI 消息管理'])
v1.include_router(conversation_transfer_router, prefix='/conversations', tags=['AI 会话导入导出'])
v1.include_router(quick_phrase_router, prefix='/quick-phrases', tags=['AI 快捷短语'])
v1.include_router(assistant_router, prefix='/assistants', tags=['AI 助手'])
v1.include_router(model_router, prefix='/models', tags=['AI 模型管理'])
v1.include_router(provider_router, prefix='/providers', tags=['AI 供应商管理'])
v1.include_router(mcp_router, prefix='/mcps', tags=['AI MCP 管理'])
v1.include_router(mcp_app_router, prefix='/conversations', tags=['AI MCP 应用'])
v1.include_router(project_router, prefix='/projects', tags=['AI 项目管理'])
v1.include_router(skill_router, prefix='/skills', tags=['AI 技能'])
v1.include_router(knowledge_base_router, prefix='/knowledges', tags=['AI 知识库'])
v1.include_router(knowledge_router, prefix='/knowledges', tags=['AI 知识文档'])
v1.include_router(artifact_router, prefix='/artifacts', tags=['AI 产物'])
v1.include_router(memory_router, prefix='/memories', tags=['AI 记忆'])
v1.include_router(expert_router, prefix='/experts', tags=['AI 专家模板'])
v1.include_router(subagent_router, prefix='/subagents', tags=['AI 子代理'])
v1.include_router(channel_router, prefix='/channels', tags=['AI 通道'])
v1.include_router(cron_router, prefix='/crons', tags=['AI 定时任务'])
v1.include_router(slash_router, prefix='/slash', tags=['AI 斜杠指令'])
v1.include_router(workspace_router, prefix='/workspaces', tags=['AI 工作区'])
v1.include_router(object_router, prefix='/objects', tags=['AI 统一对象'])
v1.include_router(attachment_router, prefix='/attachments', tags=['AI 附件'])
v1.include_router(sync_router, prefix='/sync', tags=['AI 会话同步'])

v1.include_router(approval_audit_router, prefix='/approval-audits', tags=['AI 审批审计'])

v1.include_router(mcp_oauth_router, prefix='/mcps', tags=['AI MCP OAuth'])
