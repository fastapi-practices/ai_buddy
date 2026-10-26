def build_object_key(*, user_id: int, kind: str, pk: int) -> str:
    """
    构建 Buddy 对象键

    :param user_id: 用户 ID
    :param kind: 对象类型
    :param pk: 记录 ID
    :return:
    """
    return f'ai_buddy/{user_id}/{kind}/{pk}.md'


def build_knowledge_key(*, pk: int) -> str:
    """
    构建知识对象键

    :param pk: 知识 ID
    :return:
    """
    return f'ai_buddy_knowledge/{pk}.md'


def build_skill_key(*, pk: int) -> str:
    """
    构建技能目录对象前缀

    :param pk: 技能 ID
    :return:
    """
    return f'ai_buddy/skills/{pk}'


def skill_markdown_key(object_key: str | None) -> str | None:
    """
    解析技能 SKILL.md 对象键

    :param object_key: 技能目录对象前缀
    :return:
    """
    if not object_key:
        return None
    return f'{object_key.rstrip("/")}/SKILL.md'
