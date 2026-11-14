insert into ai_buddy_mcp (user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 0, '文件系统', 'sh', 0, '读写服务器上 AI_BUDDY_MCP_FILESYSTEM_ROOT 指定的目录，默认 $HOME/ai-buddy/workspace，首次启动自动创建；仅超级管理员可运行', null, null, '["-lc", "root=\"${AI_BUDDY_MCP_FILESYSTEM_ROOT:-$HOME/ai-buddy/workspace}\"; mkdir -p \"$root\"; exec npx -y @modelcontextprotocol/server-filesystem \"$root\""]'::json, null, 120, 300, 'filesystem', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where user_id = 0 and name = '文件系统' and deleted = 0
);

insert into ai_buddy_mcp (user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 0, '网页抓取', 'sh', 0, '抓取网页正文并转换为 Markdown，首次运行自动下载依赖；需要可访问外网且已安装 uv（pipx install uv）；仅超级管理员可运行', null, null, '["-lc", "exec uvx mcp-server-fetch"]'::json, null, 120, 300, 'fetch', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where user_id = 0 and name = '网页抓取' and deleted = 0
);

insert into ai_buddy_mcp (user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 0, 'Git 仓库', 'sh', 0, '读写服务器上的 Git 仓库，需要安装 uv 并把 AI_BUDDY_MCP_GIT_REPOSITORY 设为真实仓库的绝对路径；仅超级管理员可运行', null, null, '["-lc", "repo=\"${AI_BUDDY_MCP_GIT_REPOSITORY:-$HOME}\"; exec uvx mcp-server-git --repository \"$repo\""]'::json, null, 120, 300, 'git', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where user_id = 0 and name = 'Git 仓库' and deleted = 0
);

insert into ai_buddy_mcp (user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 0, 'GitHub', null, 2, 'GitHub 官方远程 MCP（Streamable HTTP）；复制到个人配置后按 OAuth 授权或填入 Bearer 个人访问令牌', 'https://api.githubcopilot.com/mcp/', '{"Authorization": ""}'::json, null, null, 60, 300, 'github', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where user_id = 0 and name = 'GitHub' and deleted = 0
);

insert into ai_buddy_mcp (user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 0, '记忆', 'sh', 0, '基于知识图谱的长期记忆，默认保存到 $HOME/.ai-buddy/mcp-memory.jsonl，可用 AI_BUDDY_MCP_MEMORY_FILE 指定文件；仅超级管理员可运行', null, null, '["-lc", "f=\"${AI_BUDDY_MCP_MEMORY_FILE:-$HOME/.ai-buddy/mcp-memory.jsonl}\"; mkdir -p \"$(dirname \"$f\")\"; MEMORY_FILE_PATH=\"$f\" exec npx -y @modelcontextprotocol/server-memory"]'::json, null, 120, 300, 'memory', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where user_id = 0 and name = '记忆' and deleted = 0
);

insert into ai_buddy_mcp (user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 0, '时间', 'sh', 0, '查询服务器当前时间并做 IANA 时区换算，需要安装 uv；仅超级管理员可运行', null, null, '["-lc", "exec uvx mcp-server-time"]'::json, null, 120, 300, 'time', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where user_id = 0 and name = '时间' and deleted = 0
);

insert into ai_buddy_mcp (user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 0, '逐步推理', 'npx', 0, '把复杂问题拆成可回看的推理步骤，需要安装 Node.js；仅超级管理员可运行', null, null, '["-y", "@modelcontextprotocol/server-sequential-thinking"]'::json, null, 120, 300, 'thinking', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where user_id = 0 and name = '逐步推理' and deleted = 0
);

insert into ai_buddy_mcp (user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 0, '浏览器', 'npx', 0, 'Playwright 无头浏览器，支持导航、截图和表单操作，首次使用需执行 npx playwright install chromium；仅超级管理员可运行', null, null, '["-y", "@playwright/mcp@latest", "--headless", "--isolated"]'::json, null, 180, 600, 'browser', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where user_id = 0 and name = '浏览器' and deleted = 0
);
