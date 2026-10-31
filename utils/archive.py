from zipfile import ZipFile

from backend.common.exception import errors
from backend.core.conf import settings

ARCHIVE_ENTRY_MAX = 500
ARCHIVE_TOTAL_FACTOR = 4


def validate_archive_size(archive: ZipFile, *, msg: str) -> None:
    """
    读取前按声明大小限制条目数量和解压后总量，zip 只限制压缩后大小时，小文件也能展开成数 GB

    :param archive: 已打开的 zip
    :param msg: 超限时的提示
    :return:
    """
    infos = [info for info in archive.infolist() if not info.is_dir()]
    total = sum(info.file_size for info in infos)
    if len(infos) > ARCHIVE_ENTRY_MAX or total > settings.S3_UPLOAD_SIZE_MAX * ARCHIVE_TOTAL_FACTOR:
        raise errors.RequestError(msg=msg)
