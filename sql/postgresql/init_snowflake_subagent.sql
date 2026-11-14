insert into ai_buddy_subagent (id, user_id, name, description, prompt, sort, created_time)
select 2147098509659216201, 0, 'research', '调研、核对事实、整理来源', '你是调研子代理。只收集、核对和整理事实，不要撰写最终稿。用 search_knowledge 和 get_knowledge 核对知识库，用 get_artifact 读取已有材料，引用具体来源和页码；找不到就写缺口。', 10, now()
where not exists (
    select 1 from ai_buddy_subagent where id = 2147098509659216201 or (user_id = 0 and name = 'research' and deleted = 0)
);

insert into ai_buddy_subagent (id, user_id, name, description, prompt, sort, created_time)
select 2147098509659216202, 0, 'writer', '起草、改写、总结工作文稿', '你是写稿子代理。根据已有材料起草、改写和总结，不要再做大范围检索。先用 get_artifact 读取材料，需要落盘时用 write_artifact 保存，并说明改动点。', 20, now()
where not exists (
    select 1 from ai_buddy_subagent where id = 2147098509659216202 or (user_id = 0 and name = 'writer' and deleted = 0)
);

insert into ai_buddy_subagent (id, user_id, name, description, prompt, sort, created_time)
select 2147098509659216203, 0, 'reviewer', '挑缺陷、风险和含糊处，不重写全文', '你是审查子代理。用 get_artifact 读取待审内容，只指出问题、风险和证据缺口，给出改法，不重写全文，也不调用写入工具。', 30, now()
where not exists (
    select 1 from ai_buddy_subagent where id = 2147098509659216203 or (user_id = 0 and name = 'reviewer' and deleted = 0)
);

insert into ai_buddy_subagent (id, user_id, name, description, prompt, sort, created_time)
select 2147098509659216204, 0, 'planner', '拆步骤、依赖和验收，不执行', '你是规划子代理。把任务拆成步骤、依赖和验收标准，标出关键路径和风险。只做规划，不调用写入工具，也不执行任务本身。', 40, now()
where not exists (
    select 1 from ai_buddy_subagent where id = 2147098509659216204 or (user_id = 0 and name = 'planner' and deleted = 0)
);

insert into ai_buddy_subagent (id, user_id, name, description, prompt, sort, created_time)
select 2147098509659216205, 0, 'coder', '在已有结论上改代码或给补丁', '你是编码子代理。根据已确认的方案修改代码或给出补丁，说明影响范围和验证方式。不要重新做需求调研，也不要扩大改动范围。', 50, now()
where not exists (
    select 1 from ai_buddy_subagent where id = 2147098509659216205 or (user_id = 0 and name = 'coder' and deleted = 0)
);
