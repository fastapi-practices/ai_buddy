SYSTEM_OWNER_USER_ID = 0


def visible_owner_ids(user_id: int) -> list[int]:
    """
    当前用户可见的资源归属：系统内置 + 自己

    :param user_id: 当前用户 ID
    :return:
    """
    if user_id == SYSTEM_OWNER_USER_ID:
        return [SYSTEM_OWNER_USER_ID]
    return [SYSTEM_OWNER_USER_ID, user_id]


def is_visible_owner(*, owner_id: int, user_id: int) -> bool:
    """
    判断资源是否对当前用户可见

    :param owner_id: 资源归属用户 ID
    :param user_id: 当前用户 ID
    :return:
    """
    return owner_id in visible_owner_ids(user_id)
