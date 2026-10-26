insert into ai_buddy_mcp (id, user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 2147098509659216101, 0, '文件系统', 'npx', 0, '访问管理员允许的服务器目录；使用前将参数中的绝对目录占位替换为实际授权目录，仅超级管理员可运行', null, null, '["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/directory"]'::json, null, 60, 300, 'filesystem', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where id = 2147098509659216101 or (user_id = 0 and name = '文件系统' and deleted = 0)
);

insert into ai_buddy_mcp (id, user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 2147098509659216102, 0, '网页抓取', 'uvx', 0, '抓取网页正文并转换为 Markdown，需要安装 uv；仅超级管理员可运行，网络访问范围由部署环境限制', null, null, '["mcp-server-fetch"]'::json, null, 60, 300, 'fetch', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where id = 2147098509659216102 or (user_id = 0 and name = '网页抓取' and deleted = 0)
);

insert into ai_buddy_mcp (id, user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 2147098509659216103, 0, 'Git 仓库', 'uvx', 0, '读取和操作服务器 Git 仓库；使用前将绝对仓库目录占位替换为授权仓库，需要安装 uv，仅超级管理员可运行', null, null, '["mcp-server-git", "--repository", "/path/to/allowed/repository"]'::json, null, 60, 300, 'git', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where id = 2147098509659216103 or (user_id = 0 and name = 'Git 仓库' and deleted = 0)
);

insert into ai_buddy_mcp (id, user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 2147098509659216104, 0, 'GitHub', null, 2, 'GitHub 官方远程 MCP；复制到个人配置后填写 Authorization 请求头，值为 Bearer 加个人 Token', 'https://api.githubcopilot.com/mcp/', '{"Authorization": ""}'::json, null, null, 60, 300, 'github', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where id = 2147098509659216104 or (user_id = 0 and name = 'GitHub' and deleted = 0)
);

insert into ai_buddy_mcp (id, user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 2147098509659216105, 0, '记忆', 'npx', 0, '知识图谱记忆；使用前将 MEMORY_FILE_PATH 替换为独立可写持久化文件的绝对路径，仅超级管理员可运行', null, null, '["-y", "@modelcontextprotocol/server-memory"]'::json, '{"MEMORY_FILE_PATH": "/path/to/configured/mcp-memory.jsonl"}'::json, 60, 300, 'memory', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where id = 2147098509659216105 or (user_id = 0 and name = '记忆' and deleted = 0)
);

insert into ai_buddy_mcp (id, user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 2147098509659216106, 0, '时间', 'uvx', 0, '查询当前时间和转换 IANA 时区，需要安装 uv，仅超级管理员可运行', null, null, '["mcp-server-time"]'::json, null, 60, 300, 'time', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where id = 2147098509659216106 or (user_id = 0 and name = '时间' and deleted = 0)
);

insert into ai_buddy_mcp (id, user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 2147098509659216107, 0, '逐步推理', 'npx', 0, '通过连续思考步骤拆解问题，需要安装 Node.js，仅超级管理员可运行', null, null, '["-y", "@modelcontextprotocol/server-sequential-thinking"]'::json, null, 60, 300, 'thinking', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where id = 2147098509659216107 or (user_id = 0 and name = '逐步推理' and deleted = 0)
);

insert into ai_buddy_mcp (id, user_id, name, command, type, description, url, headers, args, env, timeout, read_timeout, tool_prefix, include_instructions, deleted, created_time, updated_time, deleted_time)
select 2147098509659216108, 0, '浏览器', 'npx', 0, 'Playwright 浏览器操作，使用无头和独立会话，需要安装 Node.js 与浏览器，仅超级管理员可运行', null, null, '["-y", "@playwright/mcp@latest", "--headless", "--isolated"]'::json, null, 60, 300, 'browser', false, 0, now(), null, null
where not exists (
    select 1 from ai_buddy_mcp where id = 2147098509659216108 or (user_id = 0 and name = '浏览器' and deleted = 0)
);
