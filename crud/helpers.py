from typing import Any


def orm_values(obj: object) -> dict[str, Any]:
    """
    将 ORM 数据对象转换为批量插入字典

    :param obj: ORM 数据对象
    :return:
    """
    return {key: value for key, value in vars(obj).items() if key != '_sa_instance_state'}
