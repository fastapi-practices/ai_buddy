from pydantic_ai.messages import Authority

THIRD_PARTY_DIRECTORIES: tuple[str, ...] = (
    '.git',
    '.venv',
    'build',
    'dist',
    'node_modules',
    'site-packages',
    'target',
    'vendor',
    'venv',
)
"""第三方或生成物目录，落在其中的文件对模型而言只是数据，不该被改写"""


def third_party_authority(path: str) -> Authority:
    """
    判断路径是否落在第三方目录

    :param path: 工作区相对路径
    :return:
    """
    parts = [part for part in path.replace('\\', '/').split('/') if part not in {'', '.'}]
    if any(part in THIRD_PARTY_DIRECTORIES for part in parts):
        return 'none'
    return 'user'


def authority_path_mapping() -> dict[str, Authority]:
    """
    构建第三方目录的权限等级映射

    :return:
    """
    return {f'./{name}': 'none' for name in THIRD_PARTY_DIRECTORIES}
