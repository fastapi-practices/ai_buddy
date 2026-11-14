insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '总结这段', '请用三到五条要点总结上面内容，每条一行，保留关键数字，不要发挥。', 0, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '总结这段' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '改得更短', '把上面文字压短，保留事实、结论和承诺，去掉套话和重复表达。', 10, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '改得更短' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '列出待办', '从上面内容抽出待办，每条写清动作、负责人和完成标准，缺的部分标待确认。', 20, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '列出待办' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '翻译成英文', '把上面内容翻译成英文，保留术语、数字和原有格式，不要额外解释。', 30, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '翻译成英文' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '提炼要点', '把上面内容提炼成不超过五条要点，每条一行，按重要性排序。', 40, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '提炼要点' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '换个说法', '在不改变事实和承诺的前提下，用更自然、更口语的说法重写上面内容。', 50, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '换个说法' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '找出风险', '指出上面内容里的风险、歧义和缺失信息，按严重程度排序并给出修改建议。', 60, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '找出风险' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '写成邮件', '把上面内容改成一封可以直接发送的工作邮件，包含主题、正文和明确的请求。', 70, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '写成邮件' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '整理成表格', '把上面内容整理成表格，列名具体，缺失的单元格留空并标注待补。', 80, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '整理成表格' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '结论先行', '用结论先行的方式重写：第一句给结论，后面给三条支撑理由。', 90, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '结论先行' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '逐条挑问题', '先列出上面观点的主要论点，再逐条给出反例或证据缺口，不要人身攻击。', 100, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '逐条挑问题' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '起几个标题', '根据上面内容生成 5 个具体标题，并说明每个标题适合的渠道。', 110, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '起几个标题' and deleted = 0
);
