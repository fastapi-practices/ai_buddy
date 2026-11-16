-- 内置工具权限预设由幂等 SQL 初始化，复制后可按工具自由调整
insert into ai_buddy_permission_profile (user_id, code, name, description, builtin, status, sort, created_time)
select 0, 'strict', '严格', '只读工具直接执行，写入和命令需要确认，删除类工具拒绝', true, 1, 30, now()
where not exists (
    select 1 from ai_buddy_permission_profile
    where user_id = 0 and code = 'strict' and deleted = 0
);

insert into ai_buddy_permission_profile (user_id, code, name, description, builtin, status, sort, created_time)
select 0, 'balanced', '平衡', '只读工具直接执行，写入和命令需要确认，删除类工具拒绝', true, 1, 20, now()
where not exists (
    select 1 from ai_buddy_permission_profile
    where user_id = 0 and code = 'balanced' and deleted = 0
);

insert into ai_buddy_permission_profile (user_id, code, name, description, builtin, status, sort, created_time)
select 0, 'convenience', '便捷', '常规读写直接执行，命令和外部动态工具需要确认，删除类工具拒绝', true, 1, 10, now()
where not exists (
    select 1 from ai_buddy_permission_profile
    where user_id = 0 and code = 'convenience' and deleted = 0
);

insert into ai_buddy_permission_rule (profile_id, tool_name, action, match_kind, match_value, priority, enabled, created_time)
select p.id, v.tool_name, v.action, 'any', '', 0, true, now()
from ai_buddy_permission_profile p
cross join (
    values
        ('*', 'ask'),
        ('read', 'allow'),
        ('ls', 'allow'),
        ('git_status', 'allow'),
        ('git_diff', 'allow'),
        ('bash_task_output', 'allow'),
        ('search_knowledge', 'allow'),
        ('get_knowledge', 'allow'),
        ('list_skills', 'allow'),
        ('get_skill', 'allow'),
        ('list_artifacts', 'allow'),
        ('get_artifact', 'allow'),
        ('read_skill_file', 'allow'),
        ('write', 'ask'),
        ('edit', 'ask'),
        ('bash', 'ask'),
        ('bash_background', 'ask'),
        ('bash_task_stop', 'ask'),
        ('run_tests', 'ask'),
        ('write_artifact', 'ask'),
        ('deliver_file', 'ask'),
        ('import_attachment', 'ask'),
        ('create_cron', 'ask'),
        ('set_cron_enabled', 'ask'),
        ('delete_cron', 'deny'),
        ('create_assistant', 'ask'),
        ('update_assistant', 'ask'),
        ('create_expert', 'ask'),
        ('update_expert', 'ask'),
        ('create_skill', 'ask'),
        ('update_skill', 'ask'),
        ('write_memory', 'ask'),
        ('edit_memory', 'ask'),
        ('delete_memory', 'deny'),
        ('request', 'ask'),
        ('smart_search', 'ask')
) as v(tool_name, action)
where p.user_id = 0 and p.code = 'strict' and p.deleted = 0
  and not exists (
      select 1 from ai_buddy_permission_rule r
      where r.profile_id = p.id and r.tool_name = v.tool_name
        and r.match_kind = 'any' and r.match_value = '' and r.deleted = 0
  );

insert into ai_buddy_permission_rule (profile_id, tool_name, action, match_kind, match_value, priority, enabled, created_time)
select p.id, v.tool_name, v.action, 'any', '', 0, true, now()
from ai_buddy_permission_profile p
cross join (
    values
        ('*', 'ask'),
        ('read', 'allow'),
        ('ls', 'allow'),
        ('git_status', 'allow'),
        ('git_diff', 'allow'),
        ('bash_task_output', 'allow'),
        ('search_knowledge', 'allow'),
        ('get_knowledge', 'allow'),
        ('list_skills', 'allow'),
        ('get_skill', 'allow'),
        ('list_artifacts', 'allow'),
        ('get_artifact', 'allow'),
        ('read_skill_file', 'allow'),
        ('write', 'ask'),
        ('edit', 'ask'),
        ('bash', 'ask'),
        ('bash_background', 'ask'),
        ('bash_task_stop', 'ask'),
        ('run_tests', 'ask'),
        ('write_artifact', 'ask'),
        ('deliver_file', 'ask'),
        ('import_attachment', 'ask'),
        ('create_cron', 'ask'),
        ('set_cron_enabled', 'ask'),
        ('delete_cron', 'deny'),
        ('create_assistant', 'ask'),
        ('update_assistant', 'ask'),
        ('create_expert', 'ask'),
        ('update_expert', 'ask'),
        ('create_skill', 'ask'),
        ('update_skill', 'ask'),
        ('write_memory', 'allow'),
        ('edit_memory', 'allow'),
        ('delete_memory', 'deny'),
        ('request', 'ask'),
        ('smart_search', 'ask')
) as v(tool_name, action)
where p.user_id = 0 and p.code = 'balanced' and p.deleted = 0
  and not exists (
      select 1 from ai_buddy_permission_rule r
      where r.profile_id = p.id and r.tool_name = v.tool_name
        and r.match_kind = 'any' and r.match_value = '' and r.deleted = 0
  );

insert into ai_buddy_permission_rule (profile_id, tool_name, action, match_kind, match_value, priority, enabled, created_time)
select p.id, v.tool_name, v.action, 'any', '', 0, true, now()
from ai_buddy_permission_profile p
cross join (
    values
        ('*', 'ask'),
        ('read', 'allow'),
        ('ls', 'allow'),
        ('git_status', 'allow'),
        ('git_diff', 'allow'),
        ('bash_task_output', 'allow'),
        ('search_knowledge', 'allow'),
        ('get_knowledge', 'allow'),
        ('list_skills', 'allow'),
        ('get_skill', 'allow'),
        ('list_artifacts', 'allow'),
        ('get_artifact', 'allow'),
        ('read_skill_file', 'allow'),
        ('write', 'allow'),
        ('edit', 'allow'),
        ('bash', 'ask'),
        ('bash_background', 'ask'),
        ('bash_task_stop', 'ask'),
        ('run_tests', 'allow'),
        ('write_artifact', 'allow'),
        ('deliver_file', 'allow'),
        ('import_attachment', 'allow'),
        ('create_cron', 'allow'),
        ('set_cron_enabled', 'allow'),
        ('delete_cron', 'deny'),
        ('create_assistant', 'allow'),
        ('update_assistant', 'allow'),
        ('create_expert', 'allow'),
        ('update_expert', 'allow'),
        ('create_skill', 'allow'),
        ('update_skill', 'allow'),
        ('write_memory', 'allow'),
        ('edit_memory', 'allow'),
        ('delete_memory', 'deny'),
        ('request', 'ask'),
        ('smart_search', 'ask')
) as v(tool_name, action)
where p.user_id = 0 and p.code = 'convenience' and p.deleted = 0
  and not exists (
      select 1 from ai_buddy_permission_rule r
      where r.profile_id = p.id and r.tool_name = v.tool_name
        and r.match_kind = 'any' and r.match_value = '' and r.deleted = 0
  );
