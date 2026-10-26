insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '总结这段', '请用三到五条要点总结上面内容，不要发挥。', 0, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '总结这段' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '改得更短', '把上面文字压短，保留事实和结论，去掉套话。', 1, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '改得更短' and deleted = 0
);

insert into ai_buddy_quick_phrase (user_id, title, content, sort, created_time)
select 0, '列出待办', '从上面内容抽出待办，每条包含动作和完成标准。', 2, now()
where not exists (
    select 1 from ai_buddy_quick_phrase where user_id = 0 and title = '列出待办' and deleted = 0
);
