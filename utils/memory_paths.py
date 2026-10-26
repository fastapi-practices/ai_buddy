def memory_instructions(*, project_id: int | None) -> str:
    """
    告诉模型本轮记什么、记到哪，不换存储

    :param project_id: 项目 ID
    :return:
    """
    lines = [
        '跨会话记忆文件（同一用户 Web / IM 共用，用户隔离由存储负责）：',
        '- 摘要：MEMORY.md，每轮自动读取；详细文件只在相关时使用 read_memory 读取',
        '- 档案：profile.md',
        '- 事实：fact-topic.md，请将 topic 替换为字母、数字或连字符组成的短名称',
        '- 近期：recent.md',
        '调用记忆工具时只传文件名，不要添加用户 ID、目录或斜杠',
    ]
    if project_id is not None:
        lines.append(f'- 当前项目：project-{project_id}.md')
    lines.append('助手或专家只决定本轮记哪些内容，不要改路径约定。')
    return '\n'.join(lines)


def memory_path_prefix(user_id: int) -> str:
    """
    获取当前用户记忆路径前缀

    :param user_id: 用户 ID
    :return:
    """
    return f'{user_id}/'
