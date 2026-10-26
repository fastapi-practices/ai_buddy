from collections.abc import Sequence
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import yaml

from pydantic import ValidationError

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.schema.skill import AIBuddySkillFrontmatter
from backend.plugin.ai_buddy.utils.workspace import safe_relative_parts

_SKILL_MARKDOWN_NAME = 'skill.md'
_SKILL_MARKDOWN_MAX_BYTES = 1 * 1024 * 1024
_SKILL_VERSION_MAX_CHARS = 32
_DEFAULT_SKILL_VERSION = '0.1.0'


@dataclass(frozen=True, slots=True)
class SkillUpload:
    """解析后的技能目录"""

    name: str
    description: str
    version: str
    content: str
    body: str
    files: tuple[tuple[str, bytes], ...] = ()


def skill_markdown_body(content: str) -> str:
    """
    取出技能 Markdown 正文

    :param content: 技能全文
    :return:
    """
    _, body = _split_frontmatter(content.strip())
    return body


def skill_file_guidance(skill_id: int) -> str:
    """
    说明技能包相对路径的只读访问方式

    :param skill_id: 技能 ID
    :return:
    """
    return (
        f'技能包内的相对路径请用 read_skill_file(skill_id={skill_id}, path="相对路径") 读取，'
        '较长文本可用 offset 和 limit 按字符分页；脚本只返回文本，不会执行'
    )


# 上传校验、压缩包展开和技能目录约束保持顺序一致
def parse_skill_upload(*, files: Sequence[tuple[str | None, bytes]]) -> SkillUpload:  # ruff: ignore[complex-structure]
    """
    解析上传的 Agent Skill 目录或 zip

    :param files: 技能目录文件或包含技能目录的 zip
    :return:
    """
    if not files:
        raise errors.RequestError(msg='请上传技能目录或 zip')
    payloads: list[tuple[str, bytes]] = []
    for filename, data in files:
        source = (filename or '').replace('\\', '/').strip()
        if not source:
            raise errors.RequestError(msg='文件名不能为空')
        if not data:
            raise errors.RequestError(msg='文件内容不能为空')
        if len(data) > settings.S3_UPLOAD_SIZE_MAX:
            raise errors.RequestError(msg='文件超出最大限制')
        payloads.append((source, data))
    if len(payloads) == 1 and Path(payloads[0][0]).name.lower().endswith('.zip'):
        try:
            archive = ZipFile(BytesIO(payloads[0][1]))
        except BadZipFile:
            raise errors.RequestError(msg='技能 zip 文件无效')
        with archive:
            payloads = []
            for info in archive.infolist():
                if info.is_dir():
                    continue
                parts = safe_relative_parts(info.filename, msg='技能路径包含非法路径')
                if not parts or _ignored_parts(parts):
                    continue
                if parts[-1].lower() == _SKILL_MARKDOWN_NAME and info.file_size > _SKILL_MARKDOWN_MAX_BYTES:
                    raise errors.RequestError(msg='技能文件超出最大限制')
                payloads.append(('/'.join(parts), archive.read(info.filename)))
            if not payloads:
                raise errors.RequestError(msg='未找到 SKILL.md，请上传技能目录或包含技能目录的 zip')

    skill_mds: list[tuple[str, bytes]] = []
    has_root_skill_md = False
    for filename, data in payloads:
        parts = safe_relative_parts(filename, msg='技能路径包含非法路径')
        if not parts or _ignored_parts(parts) or parts[-1].lower() != _SKILL_MARKDOWN_NAME:
            continue
        if len(parts) == 1:
            has_root_skill_md = True
            continue
        if len(parts) == 2:
            skill_mds.append((parts[0], data))
    if not skill_mds:
        if has_root_skill_md:
            raise errors.RequestError(msg='技能必须是包含 SKILL.md 的文件夹')
        raise errors.RequestError(msg='未找到 SKILL.md，请上传技能目录或包含技能目录的 zip')
    if len(skill_mds) > 1:
        raise errors.RequestError(msg='一次只能上传一个技能目录')
    directory_name, markdown_data = skill_mds[0]
    skill_files: list[tuple[str, bytes]] = []
    for filename, data in payloads:
        parts = safe_relative_parts(filename, msg='技能路径包含非法路径')
        if not parts or _ignored_parts(parts):
            continue
        if parts[0] != directory_name:
            raise errors.RequestError(msg='技能 zip 或目录只能包含一个技能文件夹')
        relative = '/'.join(parts[1:])
        if not relative:
            continue
        if relative.lower() == _SKILL_MARKDOWN_NAME:
            relative = 'SKILL.md'
        skill_files.append((relative, data))

    if len(markdown_data) > _SKILL_MARKDOWN_MAX_BYTES:
        raise errors.RequestError(msg='技能文件超出最大限制')
    try:
        text = markdown_data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise errors.RequestError(msg='技能文件必须使用 UTF-8 编码')
    uploaded = _parse_skill_markdown(text, directory_name=directory_name)
    return replace(uploaded, files=tuple(skill_files))


def _parse_skill_markdown(text: str, *, directory_name: str | None) -> SkillUpload:
    """
    按 Agent Skills 规范解析 SKILL.md

    :param text: SKILL.md 文本
    :param directory_name: 技能目录名
    :return:
    """
    content = text.strip()
    if not content:
        raise errors.RequestError(msg='技能内容不能为空')
    frontmatter_text, body = _split_frontmatter(content)
    try:
        parsed: object = yaml.load(frontmatter_text, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        raise errors.RequestError(msg='技能 YAML frontmatter 无效')
    if not isinstance(parsed, dict):
        raise errors.RequestError(msg='技能 YAML frontmatter 必须是映射')
    try:
        frontmatter = AIBuddySkillFrontmatter.model_validate(parsed)
    except ValidationError as exc:
        if any(err.get('loc', ())[:1] == ('metadata',) for err in exc.errors()):
            raise errors.RequestError(msg='技能 metadata 必须是字符串键值映射') from exc
        raise errors.RequestError(msg='技能 description 不能为空且不能超过 1024 个字符') from exc
    raw_name = frontmatter.name or directory_name
    if not raw_name:
        raise errors.RequestError(msg='技能 frontmatter 必须包含 name')
    name = _validate_skill_name(raw_name)
    if directory_name is not None and name != _validate_skill_name(directory_name):
        raise errors.RequestError(msg='技能 name 必须与所在目录名一致')
    metadata = frontmatter.metadata or {}
    version = (metadata.get('version') or '').strip() or _DEFAULT_SKILL_VERSION
    if len(version) > _SKILL_VERSION_MAX_CHARS:
        raise errors.RequestError(msg='技能 metadata.version 不能超过 32 个字符')
    return SkillUpload(
        name=name,
        description=frontmatter.description,
        version=version,
        content=content,
        body=body,
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        raise errors.RequestError(msg='技能必须包含 YAML frontmatter')
    closing = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == '---'), None)
    if closing is None:
        raise errors.RequestError(msg='技能 YAML frontmatter 未闭合')
    body_lines = lines[closing + 1 :]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    return '\n'.join(lines[1:closing]), '\n'.join(body_lines)


def _validate_skill_name(name: str) -> str:
    normalized = name.strip()
    if (
        not normalized
        or len(normalized) > 64
        or normalized != normalized.lower()
        or normalized.startswith('-')
        or normalized.endswith('-')
        or '--' in normalized
        or not all(character.isalnum() or character == '-' for character in normalized)
    ):
        raise errors.RequestError(msg='技能 name 仅支持最多 64 个小写字母、数字和单个连字符')
    return normalized


def _ignored_parts(parts: Sequence[str]) -> bool:
    return any(part == '__MACOSX' or part.startswith('.') for part in parts)
