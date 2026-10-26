do $$
declare
    ai_buddy_menu_id bigint;
    ai_buddy_default_model_menu_id bigint;
    ai_buddy_model_service_menu_id bigint;
    ai_buddy_quick_phrase_menu_id bigint;
    ai_buddy_mcp_menu_id bigint;
    ai_buddy_config_menu_id bigint;
    ai_buddy_knowledge_menu_id bigint;
    ai_buddy_skill_menu_id bigint;
    ai_buddy_assistant_menu_id bigint;
    ai_buddy_expert_menu_id bigint;
    ai_buddy_subagent_menu_id bigint;
begin
    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.menu', 'PluginAIBuddy', '/plugins/ai-buddy', 11, 'tabler:robot', 0, null, null, 1, 1, 1, '', null, null, now(), null)
    returning id into ai_buddy_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.default_model', 'AIBuddyDefaultModel', '/plugins/ai-buddy/default-model', 1, 'carbon:model-alt', 1, '/plugins/ai-buddy/views/default-model/index', 'ai:provider:list,ai:model:list', 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_default_model_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.model', 'AIBuddyModelService', '/plugins/ai-buddy/model-service', 2, 'carbon:model-alt', 1, '/plugins/ai-buddy/views/model-service/index', 'ai:provider:list,ai:model:list', 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_model_service_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.quick_phrase', 'AIBuddyQuickPhraseManage', '/plugins/ai-buddy/quick-phrase', 3, 'mdi:lightning-bolt-outline', 1, '/plugins/ai-buddy/views/quick-phrase/index', 'ai:quick-phrase:list', 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_quick_phrase_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.mcp', 'AIBuddyMcpManage', '/plugins/ai-buddy/mcp', 4, 'simple-icons:modelcontextprotocol', 1, '/plugins/ai-buddy/views/mcp/index', 'ai:mcp:list', 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_mcp_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.config', 'AIBuddyConfigManage', '/plugins/ai-buddy/config', 5, 'codicon:symbol-parameter', 1, '/plugins/ai-buddy/views/config/index', null, 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_config_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.knowledge', 'AIBuddyKnowledgeManage', '/plugins/ai-buddy/knowledge', 6, 'mdi:book-open-variant-outline', 1, '/plugins/ai-buddy/views/knowledge/index', 'ai:knowledge:list', 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_knowledge_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.skill', 'AIBuddySkillManage', '/plugins/ai-buddy/skill', 7, 'mdi:puzzle-outline', 1, '/plugins/ai-buddy/views/skill/index', 'ai:skill:list', 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_skill_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.assistant', 'AIBuddyAssistantManage', '/plugins/ai-buddy/assistant', 8, 'mdi:account-tie-outline', 1, '/plugins/ai-buddy/views/assistant/index', 'ai:assistant:list', 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_assistant_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.expert', 'AIBuddyExpertManage', '/plugins/ai-buddy/expert', 9, 'mdi:account-star-outline', 1, '/plugins/ai-buddy/views/expert/index', 'ai:expert:list', 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_expert_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values ('ai-buddy.subagent', 'AIBuddySubagentManage', '/plugins/ai-buddy/subagent', 10, 'mdi:sitemap-outline', 1, '/plugins/ai-buddy/views/subagent/index', 'ai:subagent:list', 1, 1, 1, '', null, ai_buddy_menu_id, now(), null)
    returning id into ai_buddy_subagent_menu_id;

    insert into sys_menu (title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
    values
    ('设置默认模型', 'EditAIBuddyDefaultModel', null, 0, null, 2, null, 'ai:default-model:edit', 1, 0, 1, '', null, ai_buddy_default_model_menu_id, now(), null),
    ('新增供应商', 'AddAIBuddyProvider', null, 0, null, 2, null, 'ai:provider:add', 1, 0, 1, '', null, ai_buddy_model_service_menu_id, now(), null),
    ('修改供应商', 'EditAIBuddyProvider', null, 0, null, 2, null, 'ai:provider:edit', 1, 0, 1, '', null, ai_buddy_model_service_menu_id, now(), null),
    ('删除供应商', 'DeleteAIBuddyProvider', null, 0, null, 2, null, 'ai:provider:del', 1, 0, 1, '', null, ai_buddy_model_service_menu_id, now(), null),
    ('新增模型', 'AddAIBuddyModel', null, 0, null, 2, null, 'ai:model:add', 1, 0, 1, '', null, ai_buddy_model_service_menu_id, now(), null),
    ('修改模型', 'EditAIBuddyModel', null, 0, null, 2, null, 'ai:model:edit', 1, 0, 1, '', null, ai_buddy_model_service_menu_id, now(), null),
    ('删除模型', 'DeleteAIBuddyModel', null, 0, null, 2, null, 'ai:model:del', 1, 0, 1, '', null, ai_buddy_model_service_menu_id, now(), null),
    ('新增快捷短语', 'AddAIBuddyQuickPhrase', null, 0, null, 2, null, 'ai:quick-phrase:add', 1, 0, 1, '', null, ai_buddy_quick_phrase_menu_id, now(), null),
    ('修改快捷短语', 'EditAIBuddyQuickPhrase', null, 0, null, 2, null, 'ai:quick-phrase:edit', 1, 0, 1, '', null, ai_buddy_quick_phrase_menu_id, now(), null),
    ('删除快捷短语', 'DeleteAIBuddyQuickPhrase', null, 0, null, 2, null, 'ai:quick-phrase:del', 1, 0, 1, '', null, ai_buddy_quick_phrase_menu_id, now(), null),
    ('新增MCP', 'AddAIBuddyMcp', null, 0, null, 2, null, 'ai:mcp:add', 1, 0, 1, '', null, ai_buddy_mcp_menu_id, now(), null),
    ('修改MCP', 'EditAIBuddyMcp', null, 0, null, 2, null, 'ai:mcp:edit', 1, 0, 1, '', null, ai_buddy_mcp_menu_id, now(), null),
    ('查询MCP', 'QueryAIBuddyMcp', null, 0, null, 2, null, 'ai:mcp:query', 1, 0, 1, '', null, ai_buddy_mcp_menu_id, now(), null),
    ('删除MCP', 'DeleteAIBuddyMcp', null, 0, null, 2, null, 'ai:mcp:del', 1, 0, 1, '', null, ai_buddy_mcp_menu_id, now(), null),
    ('保存配置', 'EditAIBuddyConfig', null, 0, null, 2, null, 'sys.config.edits', 1, 0, 1, '', null, ai_buddy_config_menu_id, now(), null),
    ('新增知识', 'AddAIBuddyKnowledge', null, 0, null, 2, null, 'ai:knowledge:add', 1, 0, 1, '', null, ai_buddy_knowledge_menu_id, now(), null),
    ('修改知识', 'EditAIBuddyKnowledge', null, 0, null, 2, null, 'ai:knowledge:edit', 1, 0, 1, '', null, ai_buddy_knowledge_menu_id, now(), null),
    ('删除知识', 'DeleteAIBuddyKnowledge', null, 0, null, 2, null, 'ai:knowledge:del', 1, 0, 1, '', null, ai_buddy_knowledge_menu_id, now(), null),
    ('新增技能', 'AddAIBuddySkill', null, 0, null, 2, null, 'ai:skill:add', 1, 0, 1, '', null, ai_buddy_skill_menu_id, now(), null),
    ('删除技能', 'DeleteAIBuddySkill', null, 0, null, 2, null, 'ai:skill:del', 1, 0, 1, '', null, ai_buddy_skill_menu_id, now(), null),
    ('新增助手', 'AddAIBuddyAssistant', null, 0, null, 2, null, 'ai:assistant:add', 1, 0, 1, '', null, ai_buddy_assistant_menu_id, now(), null),
    ('修改助手', 'EditAIBuddyAssistant', null, 0, null, 2, null, 'ai:assistant:edit', 1, 0, 1, '', null, ai_buddy_assistant_menu_id, now(), null),
    ('删除助手', 'DeleteAIBuddyAssistant', null, 0, null, 2, null, 'ai:assistant:del', 1, 0, 1, '', null, ai_buddy_assistant_menu_id, now(), null),
    ('新增专家', 'AddAIBuddyExpert', null, 0, null, 2, null, 'ai:expert:add', 1, 0, 1, '', null, ai_buddy_expert_menu_id, now(), null),
    ('修改专家', 'EditAIBuddyExpert', null, 0, null, 2, null, 'ai:expert:edit', 1, 0, 1, '', null, ai_buddy_expert_menu_id, now(), null),
    ('删除专家', 'DeleteAIBuddyExpert', null, 0, null, 2, null, 'ai:expert:del', 1, 0, 1, '', null, ai_buddy_expert_menu_id, now(), null),
    ('新增子代理', 'AddAIBuddySubagent', null, 0, null, 2, null, 'ai:subagent:add', 1, 0, 1, '', null, ai_buddy_subagent_menu_id, now(), null),
    ('修改子代理', 'EditAIBuddySubagent', null, 0, null, 2, null, 'ai:subagent:edit', 1, 0, 1, '', null, ai_buddy_subagent_menu_id, now(), null),
    ('删除子代理', 'DeleteAIBuddySubagent', null, 0, null, 2, null, 'ai:subagent:del', 1, 0, 1, '', null, ai_buddy_subagent_menu_id, now(), null);
end $$;

select setval(pg_get_serial_sequence('sys_menu', 'id'), coalesce(max(id), 0) + 1, true) from sys_menu;

insert into sys_config (name, type, "key", value, is_frontend, remark, created_time, updated_time)
values
('状态', 'AI', 'AI_BUDDY_CONFIG_STATUS', '1', false, null, now(), null),
('默认执行后端', 'AI', 'AI_BUDDY_AGENT_EXECUTION_BACKEND', 'local', false, '桌面 OS 沙箱 local 或远程 opensandbox', now(), null),
('Exa API Key', 'AI', 'AI_BUDDY_EXA_API_KEY', '', false, '用于 AI 联网搜索的 Exa API Key', now(), null),
('Tavily API Key', 'AI', 'AI_BUDDY_TAVILY_API_KEY', '', false, '用于 AI 联网搜索的 Tavily API Key', now(), null),
('TypeSafe API Key', 'AI', 'AI_BUDDY_TYPESAFE_API_KEY', '', false, '用于 Jev 安全判定的 TypeSafe API Key', now(), null),
('Jev 模型', 'AI', 'AI_BUDDY_JEV_MODEL', 'jev-latest', false, '用于输入和工具护栏的 Jev 模型 ID', now(), null),
('Jev 输入阈值', 'AI', 'AI_BUDDY_JEV_INPUT_THRESHOLD', '0.75', false, 'Jev 判定提示有害后拦截的概率阈值', now(), null),
('模型请求重试次数', 'AI', 'AI_BUDDY_HTTP_MAX_RETRIES', '5', false, '用于模型供应商 HTTP 请求的最大重试次数', now(), null),
('MCP 调用重试次数', 'AI', 'AI_BUDDY_MCP_MAX_RETRIES', '1', false, '用于 MCP 工具调用的最大重试次数', now(), null),
('压缩保留消息数', 'AI', 'AI_BUDDY_COMPACTION_KEEP_MESSAGES', '40', false, '控制压缩后保留的最近消息数', now(), null),
('压缩触发阈值', 'AI', 'AI_BUDDY_COMPACTION_MAX_MESSAGES', '80', false, '控制触发历史压缩的消息数阈值', now(), null),
('文档抽取', 'AI', 'AI_BUDDY_DOCUMENT_EXTRACT_BACKEND', 'native', false, '知识文档抽取后端：native、markitdown 或 unstructured', now(), null),
('Unstructured API URL', 'AI', 'AI_BUDDY_UNSTRUCTURED_API_URL', 'https://api.unstructuredapp.io/general/v0/general', false, 'Unstructured 托管或自建 API 地址', now(), null),
('Unstructured API Key', 'AI', 'AI_BUDDY_UNSTRUCTURED_API_KEY', '', false, 'Unstructured API Key，选 Unstructured 抽取时必填', now(), null),
('MarkItDown Azure Endpoint', 'AI', 'AI_BUDDY_MARKITDOWN_DOCINTEL_ENDPOINT', '', false, 'Azure 文档智能终结点，选 MarkItDown 且走云解析时填写', now(), null),
('MarkItDown Azure API Key', 'AI', 'AI_BUDDY_MARKITDOWN_DOCINTEL_API_KEY', '', false, 'Azure 文档智能 API Key。获取 https://portal.azure.com', now(), null),
('MinerU API Key', 'AI', 'AI_BUDDY_MINERU_API_KEY', '', false, 'MinerU 云解析 Token。获取 https://mineru.net/apiManage/token', now(), null),
('Open MinerU URL', 'AI', 'AI_BUDDY_OPEN_MINERU_API_URL', '', false, '自建 MinerU 服务地址', now(), null),
('Open MinerU API Key', 'AI', 'AI_BUDDY_OPEN_MINERU_API_KEY', '', false, '自建 MinerU 可选密钥', now(), null),
('Doc2X API URL', 'AI', 'AI_BUDDY_DOC2X_API_URL', 'https://v2.doc2x.noedgeai.com', false, 'Doc2X 地址。获取密钥 https://open.noedgeai.com', now(), null),
('Doc2X API Key', 'AI', 'AI_BUDDY_DOC2X_API_KEY', '', false, 'Doc2X API Key。获取 https://open.noedgeai.com', now(), null),
('Mistral API URL', 'AI', 'AI_BUDDY_MISTRAL_API_URL', 'https://api.mistral.ai', false, 'Mistral API 地址。获取密钥 https://console.mistral.ai/api-keys', now(), null),
('Mistral API Key', 'AI', 'AI_BUDDY_MISTRAL_API_KEY', '', false, 'Mistral API Key。获取 https://console.mistral.ai/api-keys', now(), null),
('向量化后端', 'AI', 'AI_BUDDY_EMBEDDING_BACKEND', 'remote', false, '知识向量化后端：remote 或 onnx', now(), null),
('ONNX 向量模型', 'AI', 'AI_BUDDY_ONNX_EMBEDDING_MODEL', 'BAAI/bge-small-zh-v1.5', false, '本地 ONNX / fastembed 向量模型 ID', now(), null),
('OCR', 'AI', 'AI_BUDDY_OCR_BACKEND', 'system', false, '知识 OCR 后端', now(), null),
('PaddleOCR URL', 'AI', 'AI_BUDDY_PADDLEOCR_API_URL', '', false, '自建 PaddleOCR 服务地址，空则使用本机 paddleocr，需先下载模型', now(), null),
('切片长度', 'AI', 'AI_BUDDY_RAG_CHUNK_CHARS', '500', false, '控制知识切片的字符长度', now(), null),
('切片重叠', 'AI', 'AI_BUDDY_RAG_CHUNK_OVERLAP', '80', false, '控制相邻知识切片的重叠字符数', now(), null),
('检索条数', 'AI', 'AI_BUDDY_RAG_TOP_K', '6', false, '控制知识语义检索返回的条数', now(), null);

select setval(pg_get_serial_sequence('sys_config', 'id'), coalesce(max(id), 0) + 1, true) from sys_config;
