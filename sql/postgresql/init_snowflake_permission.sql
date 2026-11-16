-- 内置工具权限预设由幂等 SQL 初始化，复制后可按工具自由调整
insert into ai_buddy_permission_profile (id, user_id, code, name, description, builtin, status, sort, created_time)
select 2147098509659230001, 0, 'strict', '严格', '只读工具直接执行，写入和命令需要确认，删除类工具拒绝', true, 1, 30, now()
where not exists (
    select 1 from ai_buddy_permission_profile
    where id = 2147098509659230001 or (user_id = 0 and code = 'strict' and deleted = 0)
);

insert into ai_buddy_permission_profile (id, user_id, code, name, description, builtin, status, sort, created_time)
select 2147098509659230002, 0, 'balanced', '平衡', '只读工具直接执行，写入和命令需要确认，删除类工具拒绝', true, 1, 20, now()
where not exists (
    select 1 from ai_buddy_permission_profile
    where id = 2147098509659230002 or (user_id = 0 and code = 'balanced' and deleted = 0)
);

insert into ai_buddy_permission_profile (id, user_id, code, name, description, builtin, status, sort, created_time)
select 2147098509659230003, 0, 'convenience', '便捷', '常规读写直接执行，命令和外部动态工具需要确认，删除类工具拒绝', true, 1, 10, now()
where not exists (
    select 1 from ai_buddy_permission_profile
    where id = 2147098509659230003 or (user_id = 0 and code = 'convenience' and deleted = 0)
);
-- strict 预设规则
insert into ai_buddy_permission_rule (id, profile_id, tool_name, action, match_kind, match_value, priority, enabled, created_time)
select
    2147098509659240000 + v.tool_order,
    p.id,
    v.tool_name,
    v.action,
    'any',
    '',
    0,
    true,
    now()
from ai_buddy_permission_profile p
cross join (
    values
        (1, '*', 'ask'),
        (2, 'read', 'allow'),
        (3, 'ls', 'allow'),
        (4, 'git_status', 'allow'),
        (5, 'git_diff', 'allow'),
        (6, 'bash_task_output', 'allow'),
        (7, 'search_knowledge', 'allow'),
        (8, 'get_knowledge', 'allow'),
        (9, 'list_skills', 'allow'),
        (10, 'get_skill', 'allow'),
        (11, 'list_artifacts', 'allow'),
        (12, 'get_artifact', 'allow'),
        (13, 'read_skill_file', 'allow'),
        (14, 'write', 'ask'),
        (15, 'edit', 'ask'),
        (16, 'bash', 'ask'),
        (17, 'bash_background', 'ask'),
        (18, 'bash_task_stop', 'ask'),
        (19, 'run_tests', 'ask'),
        (20, 'write_artifact', 'ask'),
        (21, 'deliver_file', 'ask'),
        (22, 'import_attachment', 'ask'),
        (23, 'create_cron', 'ask'),
        (24, 'set_cron_enabled', 'ask'),
        (25, 'delete_cron', 'deny'),
        (26, 'create_assistant', 'ask'),
        (27, 'update_assistant', 'ask'),
        (28, 'create_expert', 'ask'),
        (29, 'update_expert', 'ask'),
        (30, 'create_skill', 'ask'),
        (31, 'update_skill', 'ask'),
        (32, 'write_memory', 'ask'),
        (33, 'edit_memory', 'ask'),
        (34, 'delete_memory', 'deny'),
        (35, 'request', 'ask'),
        (36, 'smart_search', 'ask')
) as v(tool_order, tool_name, action)
where p.id = 2147098509659230001 and p.deleted = 0
on conflict do nothing;
-- balanced 预设规则
insert into ai_buddy_permission_rule (id, profile_id, tool_name, action, match_kind, match_value, priority, enabled, created_time)
select
    2147098509659240036 + v.tool_order,
    p.id,
    v.tool_name,
    v.action,
    'any',
    '',
    0,
    true,
    now()
from ai_buddy_permission_profile p
cross join (
    values
        (1, '*', 'ask'),
        (2, 'read', 'allow'),
        (3, 'ls', 'allow'),
        (4, 'git_status', 'allow'),
        (5, 'git_diff', 'allow'),
        (6, 'bash_task_output', 'allow'),
        (7, 'search_knowledge', 'allow'),
        (8, 'get_knowledge', 'allow'),
        (9, 'list_skills', 'allow'),
        (10, 'get_skill', 'allow'),
        (11, 'list_artifacts', 'allow'),
        (12, 'get_artifact', 'allow'),
        (13, 'read_skill_file', 'allow'),
        (14, 'write', 'ask'),
        (15, 'edit', 'ask'),
        (16, 'bash', 'ask'),
        (17, 'bash_background', 'ask'),
        (18, 'bash_task_stop', 'ask'),
        (19, 'run_tests', 'ask'),
        (20, 'write_artifact', 'ask'),
        (21, 'deliver_file', 'ask'),
        (22, 'import_attachment', 'ask'),
        (23, 'create_cron', 'ask'),
        (24, 'set_cron_enabled', 'ask'),
        (25, 'delete_cron', 'deny'),
        (26, 'create_assistant', 'ask'),
        (27, 'update_assistant', 'ask'),
        (28, 'create_expert', 'ask'),
        (29, 'update_expert', 'ask'),
        (30, 'create_skill', 'ask'),
        (31, 'update_skill', 'ask'),
        (32, 'write_memory', 'allow'),
        (33, 'edit_memory', 'allow'),
        (34, 'delete_memory', 'deny'),
        (35, 'request', 'ask'),
        (36, 'smart_search', 'ask')
) as v(tool_order, tool_name, action)
where p.id = 2147098509659230002 and p.deleted = 0
on conflict do nothing;
-- convenience 预设规则
insert into ai_buddy_permission_rule (id, profile_id, tool_name, action, match_kind, match_value, priority, enabled, created_time)
select
    2147098509659240072 + v.tool_order,
    p.id,
    v.tool_name,
    v.action,
    'any',
    '',
    0,
    true,
    now()
from ai_buddy_permission_profile p
cross join (
    values
        (1, '*', 'ask'),
        (2, 'read', 'allow'),
        (3, 'ls', 'allow'),
        (4, 'git_status', 'allow'),
        (5, 'git_diff', 'allow'),
        (6, 'bash_task_output', 'allow'),
        (7, 'search_knowledge', 'allow'),
        (8, 'get_knowledge', 'allow'),
        (9, 'list_skills', 'allow'),
        (10, 'get_skill', 'allow'),
        (11, 'list_artifacts', 'allow'),
        (12, 'get_artifact', 'allow'),
        (13, 'read_skill_file', 'allow'),
        (14, 'write', 'allow'),
        (15, 'edit', 'allow'),
        (16, 'bash', 'ask'),
        (17, 'bash_background', 'ask'),
        (18, 'bash_task_stop', 'ask'),
        (19, 'run_tests', 'allow'),
        (20, 'write_artifact', 'allow'),
        (21, 'deliver_file', 'allow'),
        (22, 'import_attachment', 'allow'),
        (23, 'create_cron', 'allow'),
        (24, 'set_cron_enabled', 'allow'),
        (25, 'delete_cron', 'deny'),
        (26, 'create_assistant', 'allow'),
        (27, 'update_assistant', 'allow'),
        (28, 'create_expert', 'allow'),
        (29, 'update_expert', 'allow'),
        (30, 'create_skill', 'allow'),
        (31, 'update_skill', 'allow'),
        (32, 'write_memory', 'allow'),
        (33, 'edit_memory', 'allow'),
        (34, 'delete_memory', 'deny'),
        (35, 'request', 'ask'),
        (36, 'smart_search', 'ask')
) as v(tool_order, tool_name, action)
where p.id = 2147098509659230003 and p.deleted = 0
on conflict do nothing;
