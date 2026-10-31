delete from sys_menu
where name in (
    'AIBuddyDefaultModel',
    'EditAIBuddyDefaultModel',
    'AIBuddyModelService',
    'AddAIBuddyProvider',
    'EditAIBuddyProvider',
    'DeleteAIBuddyProvider',
    'AddAIBuddyModel',
    'EditAIBuddyModel',
    'DeleteAIBuddyModel',
    'AIBuddyQuickPhraseManage',
    'AddAIBuddyQuickPhrase',
    'EditAIBuddyQuickPhrase',
    'DeleteAIBuddyQuickPhrase',
    'AIBuddyMcpManage',
    'AddAIBuddyMcp',
    'EditAIBuddyMcp',
    'QueryAIBuddyMcp',
    'DeleteAIBuddyMcp',
    'AIBuddyConfigManage',
    'EditAIBuddyConfig',
    'AIBuddyKnowledgeManage',
    'AddAIBuddyKnowledge',
    'EditAIBuddyKnowledge',
    'DeleteAIBuddyKnowledge',
    'AIBuddySkillManage',
    'AddAIBuddySkill',
    'DeleteAIBuddySkill',
    'AIBuddyAssistantManage',
    'AddAIBuddyAssistant',
    'EditAIBuddyAssistant',
    'DeleteAIBuddyAssistant',
    'AIBuddyExpertManage',
    'AddAIBuddyExpert',
    'EditAIBuddyExpert',
    'DeleteAIBuddyExpert',
    'AIBuddySubagentManage',
    'AddAIBuddySubagent',
    'EditAIBuddySubagent',
    'DeleteAIBuddySubagent'
);

delete from sys_menu where name = 'PluginAIBuddy';

delete from sys_config
where "key" in (
    'AI_BUDDY_CONFIG_STATUS',
    'AI_BUDDY_AGENT_EXECUTION_BACKEND',
    'AI_BUDDY_EXA_API_KEY',
    'AI_BUDDY_TAVILY_API_KEY',
    'AI_BUDDY_TYPESAFE_API_KEY',
    'AI_BUDDY_JEV_MODEL',
    'AI_BUDDY_JEV_INPUT_THRESHOLD',
    'AI_BUDDY_HTTP_MAX_RETRIES',
    'AI_BUDDY_MCP_MAX_RETRIES',
    'AI_BUDDY_COMPACTION_KEEP_MESSAGES',
    'AI_BUDDY_COMPACTION_MAX_MESSAGES',
    'AI_BUDDY_DOCUMENT_EXTRACT_BACKEND',
    'AI_BUDDY_UNSTRUCTURED_API_URL',
    'AI_BUDDY_UNSTRUCTURED_API_KEY',
    'AI_BUDDY_MARKITDOWN_DOCINTEL_ENDPOINT',
    'AI_BUDDY_MARKITDOWN_DOCINTEL_API_KEY',
    'AI_BUDDY_MINERU_API_KEY',
    'AI_BUDDY_OPEN_MINERU_API_URL',
    'AI_BUDDY_OPEN_MINERU_API_KEY',
    'AI_BUDDY_DOC2X_API_URL',
    'AI_BUDDY_DOC2X_API_KEY',
    'AI_BUDDY_MISTRAL_API_URL',
    'AI_BUDDY_MISTRAL_API_KEY',
    'AI_BUDDY_EMBEDDING_BACKEND',
    'AI_BUDDY_ONNX_EMBEDDING_MODEL',
    'AI_BUDDY_OCR_BACKEND',
    'AI_BUDDY_PADDLEOCR_API_URL',
    'AI_BUDDY_RAG_CHUNK_CHARS',
    'AI_BUDDY_RAG_CHUNK_OVERLAP',
    'AI_BUDDY_RAG_TOP_K'
);

drop table if exists ai_buddy_memory_operation;
drop table if exists ai_buddy_memory_file;
drop table if exists ai_buddy_message_error;
drop table if exists ai_buddy_message;
drop table if exists ai_buddy_follow_up;
drop table if exists ai_buddy_conversation;
drop table if exists ai_buddy_artifact;
drop table if exists ai_buddy_knowledge;
drop table if exists ai_buddy_knowledge_base;
drop table if exists ai_buddy_skill;
drop table if exists ai_buddy_assistant;
drop table if exists ai_buddy_expert;
drop table if exists ai_buddy_subagent;
drop table if exists ai_buddy_channel_user;
drop table if exists ai_buddy_channel;
drop table if exists ai_buddy_cron;
drop table if exists ai_buddy_quick_phrase;
drop table if exists ai_buddy_default_model;
drop table if exists ai_buddy_model;
drop table if exists ai_buddy_provider;
drop table if exists ai_buddy_mcp;
drop table if exists ai_buddy_project;

select setval(pg_get_serial_sequence('sys_menu', 'id'), coalesce(max(id), 0) + 1, true) from sys_menu;

drop table if exists ai_buddy_workspace_file;
drop table if exists ai_buddy_workspace;

drop table if exists ai_buddy_sandbox_workspace;
drop table if exists ai_buddy_step_tool_effect;
drop table if exists ai_buddy_step_snapshot;
drop table if exists ai_buddy_step_message;
drop table if exists ai_buddy_step_event;
drop table if exists ai_buddy_step_run;
drop table if exists ai_buddy_object_audit;
drop table if exists ai_buddy_object_ref;
drop table if exists ai_buddy_object;
drop table if exists ai_buddy_conversation_audit;
drop table if exists ai_buddy_approval_audit;
drop table if exists ai_buddy_mcp_oauth;
drop table if exists ai_buddy_mcp_oauth_config;

DROP TABLE IF EXISTS ai_buddy_approval_audit;

DROP TABLE IF EXISTS ai_buddy_mcp_oauth;
DROP TABLE IF EXISTS ai_buddy_mcp_oauth_config;
