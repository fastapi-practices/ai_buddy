import re

from collections.abc import Sequence
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.ai_buddy.crud.crud_skill import ai_buddy_skill_dao
from backend.plugin.ai_buddy.enums import AIBuddyObjectKind, AIBuddyObjectLocation
from backend.plugin.ai_buddy.model.skill import SYSTEM_SKILL_USER_ID, AIBuddySkill
from backend.plugin.ai_buddy.schema.skill import (
    CreateAIBuddySkillParam,
    GetAIBuddySkillSearchDetail,
    UpdateAIBuddySkillParam,
)
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service
from backend.plugin.ai_buddy.utils.object_key import build_skill_key, skill_markdown_key
from backend.plugin.ai_buddy.utils.skill_parser import parse_skill_upload, rewrite_skill_markdown
from backend.plugin.s3.service.storage_service import s3_storage_service
from backend.plugin.s3.utils.file_ops import get_operator
from backend.plugin.s3.utils.text_store import read_text, require_storage, write_bytes

_SKILL_FILE_MAX_BYTES = 1024 * 1024
_SKILL_FILE_PAGE_CHARS = 12000


class AIBuddySkillService:
    """AI 技能服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int, include_content: bool = True) -> Sequence[AIBuddySkill]:
        """
        获取当前用户可用的所有技能

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param include_content: 是否从对象存储读取技能正文
        :return:
        """
        skills = await ai_buddy_skill_dao.get_all(db, user_id)
        if include_content:
            for skill in skills:
                skill.content = await read_text(
                    db=db, key=skill_markdown_key(skill.object_key), storage_id=skill.storage_id
                )
        return skills

    @staticmethod
    async def search(*, db: AsyncSession, user_id: int, query: str) -> list[GetAIBuddySkillSearchDetail]:
        """
        搜索当前用户可见的系统与自有技能

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param query: 搜索词
        :return:
        """
        keyword = query.strip()
        if not keyword:
            raise errors.RequestError(msg='请输入搜索词')
        skills = await ai_buddy_skill_dao.search(db, user_id, keyword)
        return [GetAIBuddySkillSearchDetail.model_validate(item) for item in skills]

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int) -> AIBuddySkill:
        """
        获取技能详情

        :param db: 数据库会话
        :param pk: 技能 ID
        :param user_id: 用户 ID
        :return:
        """
        skill = await ai_buddy_skill_dao.get_by_id_and_user_id(db, pk, user_id)
        if not skill:
            raise errors.NotFoundError(msg='技能不存在')
        skill.content = await read_text(db=db, key=skill_markdown_key(skill.object_key), storage_id=skill.storage_id)
        return skill

    async def read_file(
        self,
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
        path: str,
        offset: int = 0,
        limit: int = _SKILL_FILE_PAGE_CHARS,
    ) -> str:
        """
        校验权限并分页读取技能包内 UTF-8 文本，不执行脚本

        :param db: 数据库会话
        :param pk: 主键 ID
        :param user_id: 用户 ID
        :param path: 文件路径
        :param offset: 起始偏移量
        :param limit: 数量上限
        :return:
        """
        if offset < 0 or not 1 <= limit <= _SKILL_FILE_PAGE_CHARS:
            raise errors.RequestError(msg=f'offset 不能为负数，limit 必须在 1 到 {_SKILL_FILE_PAGE_CHARS} 之间')
        skill = await ai_buddy_skill_dao.get_by_id_and_user_id(db, pk, user_id)
        if skill is None:
            raise errors.NotFoundError(msg='技能不存在')
        key, filename = self._skill_file_key(object_key=skill.object_key, path=path)
        storage = await s3_storage_service.get_default(db=db)
        operator = get_operator(storage)
        try:
            metadata = await operator.stat(key)
        except Exception as exc:
            raise errors.NotFoundError(msg='技能文件不存在或不可读取') from exc
        if metadata.content_length > _SKILL_FILE_MAX_BYTES:
            raise errors.RequestError(msg='技能文件超过 1 MiB 文本读取上限')
        read_options: dict[str, Any] = {'size': metadata.content_length}
        if metadata.etag:
            read_options['if_match'] = metadata.etag
        try:
            data = bytes(await operator.read(key, **read_options)) if metadata.content_length else b''
        except Exception as exc:
            raise errors.NotFoundError(msg='技能文件不存在或不可读取') from exc
        if len(data) > _SKILL_FILE_MAX_BYTES:
            raise errors.RequestError(msg='技能文件超过 1 MiB 文本读取上限')
        try:
            content = data.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise errors.RequestError(msg='技能文件不是 UTF-8 文本') from exc
        if '\x00' in content:
            raise errors.RequestError(msg='技能文件不是可读取的文本')
        page = content[offset : offset + limit]
        next_offset = offset + len(page)
        suffix = f'\n…后续内容请使用 offset={next_offset} 继续读取' if next_offset < len(content) else ''
        return (
            f'## 技能 #{skill.id} 文件：{filename}（字符 {offset}-{next_offset}，共 {len(content)}）\n\n{page}{suffix}'
        )

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        name: str | None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """
        获取技能列表

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 技能名称
        :param is_superuser: 是否为超级管理员
        :return:
        """
        skill_select = await ai_buddy_skill_dao.get_select(None if is_superuser else user_id, name)
        page_data = await paging_data(db, skill_select)
        for item in page_data.get('items') or []:
            object_key = skill_markdown_key(item.get('object_key'))
            item['content'] = await read_text(db=db, key=object_key, storage_id=item.get('storage_id'))
        return page_data

    async def create(self, *, db: AsyncSession, user_id: int, files: Sequence[UploadFile]) -> None:
        """
        上传并创建技能

        :param db: 数据库会话
        :param user_id: 上传用户 ID
        :param files: 技能目录或包含技能目录的 zip
        :return:
        """
        payloads = [(item.filename, await item.read()) for item in files]
        await self.create_from_payloads(db=db, user_id=user_id, payloads=payloads)

    async def create_from_payloads(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        payloads: Sequence[tuple[str | None, bytes]],
    ) -> None:
        """
        按文件内容创建技能

        :param db: 数据库会话
        :param user_id: 所属用户 ID
        :param payloads: 技能目录文件列表，路径以技能目录名开头
        :return:
        """
        uploaded = await run_in_threadpool(parse_skill_upload, files=payloads)
        if await ai_buddy_skill_dao.get_by_name(db, user_id, uploaded.name):
            raise errors.ConflictError(msg='技能名称已存在')
        skill = await ai_buddy_skill_dao.create(
            db,
            user_id,
            CreateAIBuddySkillParam(
                name=uploaded.name,
                description=uploaded.description,
                version=uploaded.version,
            ),
        )
        object_key = build_skill_key(pk=skill.id)
        files = uploaded.files or (('SKILL.md', uploaded.content.encode()),)
        storage = await require_storage(db=db)
        for relative, data in files:
            await write_bytes(db=db, key=f'{object_key}/{relative}', data=data, storage_id=storage.id)
        skill.object_key = object_key
        skill.storage_id = storage.id
        await db.flush()
        await self._track_object(db=db, skill=skill, released=False)

    @staticmethod
    async def update_content(
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
        description: str | None,
        body: str | None,
        version: str | None,
    ) -> None:
        """
        原地改写本人技能的 SKILL.md，技能 ID 和包内其他文件保持不变，参数为空表示保持原值

        :param db: 数据库会话
        :param pk: 技能 ID
        :param user_id: 用户 ID
        :param description: 新描述
        :param body: 新正文
        :param version: 新版本
        :return:
        """
        skill = await ai_buddy_skill_dao.get(db, pk)
        if skill is None or skill.user_id not in {user_id, SYSTEM_SKILL_USER_ID}:
            raise errors.NotFoundError(msg='技能不存在')
        if skill.user_id == SYSTEM_SKILL_USER_ID:
            raise errors.ForbiddenError(msg='系统内置技能不允许修改')
        key = skill_markdown_key(skill.object_key)
        current = await read_text(db=db, key=key, storage_id=skill.storage_id)
        content = rewrite_skill_markdown(current, description=description, body=body, version=version)
        uploaded = await run_in_threadpool(parse_skill_upload, files=[(f'{skill.name}/SKILL.md', content.encode())])
        await ai_buddy_skill_dao.update(
            db,
            pk,
            UpdateAIBuddySkillParam(name=skill.name, description=uploaded.description, version=uploaded.version),
        )
        await write_bytes(db=db, key=key, data=uploaded.content.encode(), storage_id=skill.storage_id)

    async def sync_builtin(self, *, db: AsyncSession, payloads: Sequence[tuple[str | None, bytes]]) -> bool:
        """
        写入或升级随插件发布的内置技能，库中已是同版本或更高版本时跳过

        :param db: 数据库会话
        :param payloads: 技能目录文件列表，路径以技能目录名开头
        :return:
        """
        uploaded = await run_in_threadpool(parse_skill_upload, files=payloads)
        existing = await ai_buddy_skill_dao.get_by_name(db, SYSTEM_SKILL_USER_ID, uploaded.name)
        if existing:
            if _version_key(existing.version) >= _version_key(uploaded.version):
                return False
            await self.delete(db=db, pk=existing.id, user_id=SYSTEM_SKILL_USER_ID, is_superuser=True)
        await self.create_from_payloads(db=db, user_id=SYSTEM_SKILL_USER_ID, payloads=payloads)
        return True

    async def delete(self, *, db: AsyncSession, pk: int, user_id: int, is_superuser: bool) -> int:
        """
        删除技能

        :param db: 数据库会话
        :param pk: 技能 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        skill = await ai_buddy_skill_dao.get(db, pk)
        if skill is None:
            raise errors.NotFoundError(msg='技能不存在')
        if skill.user_id == SYSTEM_SKILL_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统内置技能不允许删除')
        if skill.user_id not in {user_id, SYSTEM_SKILL_USER_ID} and not is_superuser:
            raise errors.ForbiddenError(msg='技能不存在')
        await self._track_object(db=db, skill=skill, released=True)
        return await ai_buddy_skill_dao.delete(db, pk, skill.user_id)

    @staticmethod
    async def _track_object(*, db: AsyncSession, skill: AIBuddySkill, released: bool) -> None:
        """
        同步技能包目录与统一对象的引用，目录以 / 结尾登记，删除时只释放引用，由回收任务在宽限期后清理

        :param db: 数据库会话
        :param skill: 技能记录
        :param released: 是否释放引用
        :return:
        """
        if not skill.object_key or skill.storage_id is None:
            return
        stored = await ai_buddy_object_service.register(
            db=db,
            user_id=skill.user_id,
            kind=AIBuddyObjectKind.skill,
            location=AIBuddyObjectLocation.s3,
            object_key=f'{skill.object_key.rstrip("/")}/',
            storage_id=skill.storage_id,
        )
        track = ai_buddy_object_service.remove_reference if released else ai_buddy_object_service.add_reference
        await track(db=db, obj=stored, owner_type='skill', owner_id=str(skill.id), actor_id=None)

    @staticmethod
    def _skill_file_key(*, object_key: str | None, path: str) -> tuple[str, str]:
        """
        将相对文件路径限制在技能包对象前缀内

        :param object_key: 对象键
        :param path: 文件路径
        :return:
        """
        relative = path.strip().replace('\\', '/')
        parts = PurePosixPath(relative).parts
        if (
            not parts
            or relative.endswith('/')
            or PurePosixPath(relative).is_absolute()
            or PureWindowsPath(relative).drive
            or '..' in parts
            or any(ord(char) < 32 for char in relative)
        ):
            raise errors.RequestError(msg='技能文件路径必须是包内相对文件路径')
        prefix = (object_key or '').strip().rstrip('/')
        if (
            not PurePosixPath(prefix).parts
            or PurePosixPath(prefix).is_absolute()
            or '\\' in prefix
            or '..' in PurePosixPath(prefix).parts
            or any(ord(char) < 32 for char in prefix)
        ):
            raise errors.RequestError(msg='技能文件目录无效')
        filename = '/'.join(parts)
        return f'{prefix}/{filename}', filename


def _version_key(version: str) -> tuple[int, ...]:
    """
    将技能版本转换为可比较的数字元组

    :param version: 技能版本
    :return:
    """
    return tuple(int(part) for part in re.findall(r'\d+', version))


ai_buddy_skill_service: AIBuddySkillService = AIBuddySkillService()
