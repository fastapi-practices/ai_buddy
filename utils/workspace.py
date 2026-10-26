import re

from pathlib import PurePosixPath

from backend.common.exception import errors

_WORKSPACE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,128}$')


def normalize_workspace_path(path: str) -> str:
    """
    规范化工作区内的相对路径

    :param path: 工作区相对路径
    :return:
    """
    if not isinstance(path, str) or len(path) > 4096 or any(char in path for char in ('\0', '\n', '\r')):
        raise errors.RequestError(msg='工作区文件路径非法')
    normalized = path.replace('\\', '/').strip()
    if not normalized or normalized.startswith(('/', '~/')) or normalized == '~' or ':' in normalized.split('/')[0]:
        raise errors.RequestError(msg='工作区文件路径必须是相对路径')
    parts = normalized.split('/')
    if any(not part or part in {'.', '..'} for part in parts):
        raise errors.RequestError(msg='工作区文件路径不能包含空路径或上级目录')
    return '/'.join(parts)


def validate_workspace_id(workspace_id: str) -> str:
    """
    校验工作区标识

    :param workspace_id: 工作区标识
    :return:
    """
    if not isinstance(workspace_id, str) or not _WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
        raise errors.RequestError(msg='工作区标识非法')
    return workspace_id


def normalize_workspace_object_prefix(*, user_id: int, workspace_id: str, prefix: str | None) -> str:
    """
    校验工作区对象前缀属于当前用户和工作区

    :param user_id: 用户 ID
    :param workspace_id: 工作区标识
    :param prefix: 对象前缀
    :return:
    """
    workspace = validate_workspace_id(workspace_id)
    expected = f'ai_buddy/workspaces/{user_id}/{workspace}'
    if prefix is None:
        return expected
    normalized = prefix.strip().strip('/')
    parts = normalized.split('/')
    if (
        not normalized
        or any(not part or part in {'.', '..'} for part in parts)
        or any(ord(char) < 32 for char in normalized)
        or (normalized != expected and not normalized.startswith(f'{expected}/'))
    ):
        raise errors.RequestError(msg='工作区对象前缀非法')
    return normalized


def safe_relative_parts(filename: str, *, msg: str) -> list[str]:
    """
    拆分上传文件路径并拒绝绝对路径和上级目录

    :param filename: 文件路径
    :param msg: 路径非法时的错误信息
    :return:
    """
    path = PurePosixPath(filename.replace('\\', '/'))
    if path.is_absolute() or '..' in path.parts:
        raise errors.RequestError(msg=msg)
    return [part for part in path.parts if part not in {'.', ''}]
