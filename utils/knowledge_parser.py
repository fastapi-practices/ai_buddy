from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.enums import AIBuddyDocumentExtractBackend, AIBuddyKnowledgeFileType
from backend.plugin.ai_buddy.utils.archive import validate_archive_size
from backend.plugin.ai_buddy.utils.knowledge_extract import extract_with_backend
from backend.plugin.ai_buddy.utils.workspace import safe_relative_parts

_TEXT_EXTS = frozenset({'md', 'markdown', 'txt', 'text'})
_OFFICE_EXTS = frozenset({'pdf', 'docx', 'pptx', 'xlsx'})
_IMAGE_EXTS = frozenset({'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tif', 'tiff'})
_KNOWLEDGE_EXTS = _TEXT_EXTS | _OFFICE_EXTS | _IMAGE_EXTS
_IMAGE_MEDIA_TYPES = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'webp': 'image/webp',
    'gif': 'image/gif',
    'bmp': 'image/bmp',
    'tif': 'image/tiff',
    'tiff': 'image/tiff',
}


@dataclass(frozen=True, slots=True)
class KnowledgeSegment:
    """知识解析片段"""

    text: str | None = None
    image: bytes | None = None
    media_type: str | None = None
    placeholder: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeUpload:
    """解析后的知识文件"""

    title: str
    content: str
    source: str
    file_type: AIBuddyKnowledgeFileType
    segments: tuple[KnowledgeSegment, ...] = ()


def _resolve_document_extract_backend(value: str | None = None) -> AIBuddyDocumentExtractBackend:
    """
    解析文档抽取后端，非法值回退内置解析

    :param value: 配置原文，空则读取当前配置
    :return:
    """
    text = (value if value is not None else settings.AI_BUDDY_DOCUMENT_EXTRACT_BACKEND) or ''
    try:
        return AIBuddyDocumentExtractBackend(str(text).strip().lower())
    except ValueError:
        return AIBuddyDocumentExtractBackend.native


# 目录、压缩包与文件格式校验共同决定本次上传结果
def parse_knowledge_uploads(  # ruff: ignore[complex-structure]
    *,
    files: Sequence[tuple[str | None, bytes]],
    title: str | None = None,
) -> list[KnowledgeUpload]:
    """
    解析上传的知识文件、目录或 zip

    :param files: 知识文件、目录或包含 md、txt 的 zip
    :param title: 可选标题，仅单个文件时生效，空值使用文件名
    :return:
    """
    if not files:
        raise errors.RequestError(msg='请上传知识文件、目录或 zip')
    payloads: list[tuple[str, bytes]] = []
    for filename, data in files:
        source = (filename or '').replace('\\', '/').strip()
        if not source:
            raise errors.RequestError(msg='文件名不能为空')
        if not data:
            raise errors.RequestError(msg='文件内容不能为空')
        if len(data) > settings.S3_UPLOAD_SIZE_MAX:
            raise errors.RequestError(msg='文件超出最大限制')
        name = Path(source).name
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        if ext != 'zip' and ext not in _KNOWLEDGE_EXTS:
            raise errors.RequestError(msg='知识仅支持 md、txt、pdf、docx、pptx、xlsx、图片或包含这些文件的 zip')
        payloads.append((source, data))
    documents: list[tuple[str, bytes]] = []
    for filename, data in payloads:
        if Path(filename).name.lower().endswith('.zip'):
            try:
                archive = ZipFile(BytesIO(data))
            except BadZipFile as exc:
                raise errors.RequestError(msg='知识 zip 文件无效') from exc
            with archive:
                validate_archive_size(archive, msg='知识 zip 解压后超出最大限制')
                entries: list[tuple[str, bytes]] = []
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    parts = safe_relative_parts(info.filename, msg='知识路径包含非法路径')
                    if not parts or any(part == '__MACOSX' or part.startswith('.') for part in parts):
                        continue
                    ext = parts[-1].rsplit('.', 1)[-1].lower() if '.' in parts[-1] else ''
                    if ext not in _KNOWLEDGE_EXTS:
                        continue
                    with archive.open(info) as file:
                        content = file.read(settings.S3_UPLOAD_SIZE_MAX + 1)
                    if len(content) > settings.S3_UPLOAD_SIZE_MAX:
                        raise errors.RequestError(msg='文件超出最大限制')
                    entries.append(('/'.join(parts), content))
                if not entries:
                    raise errors.RequestError(msg='zip 中未找到可解析的知识文件')
                documents.extend(entries)
            continue
        documents.append((filename, data))
    if not documents:
        raise errors.RequestError(msg='未找到可解析的知识文件')
    resolved_title = (title or '').strip() or None
    if resolved_title and len(documents) > 1:
        raise errors.RequestError(msg='批量上传不能指定标题')
    uploads: list[KnowledgeUpload] = []
    for filename, data in documents:
        source = '/'.join(safe_relative_parts(filename, msg='知识路径包含非法路径'))
        if not source:
            raise errors.RequestError(msg='文件名不能为空')
        ext = Path(source).suffix.lower().lstrip('.')
        file_type = (
            AIBuddyKnowledgeFileType.image
            if ext in _IMAGE_EXTS
            else AIBuddyKnowledgeFileType({'markdown': 'md', 'text': 'txt'}.get(ext, ext))
        )
        segments: list[KnowledgeSegment] = []
        if ext in _TEXT_EXTS:
            try:
                text = data.decode('utf-8-sig').strip()
            except UnicodeDecodeError as exc:
                raise errors.RequestError(msg='文本知识文件必须使用 UTF-8 编码') from exc
            if text:
                segments.append(KnowledgeSegment(text=text))
        elif ext in _IMAGE_EXTS:
            segments.append(
                KnowledgeSegment(
                    image=data,
                    media_type=_IMAGE_MEDIA_TYPES.get(ext, 'application/octet-stream'),
                    placeholder=f'[image] {Path(source).name}',
                )
            )
        else:
            backend = _resolve_document_extract_backend()
            if backend != AIBuddyDocumentExtractBackend.native and ext in _OFFICE_EXTS:
                text = extract_with_backend(backend=backend, filename=source, data=data, ext=ext)
                if text:
                    segments.append(KnowledgeSegment(text=text))
                elif ext == 'pdf':
                    segments = _extract_pdf_segments(data)
            elif ext == 'pdf':
                segments = _extract_pdf_segments(data)
            else:
                if ext == 'docx':
                    try:
                        from docx import Document
                    except ImportError as exc:
                        raise errors.RequestError(msg='解析 docx 需要安装 python-docx') from exc
                    document = Document(BytesIO(data))
                    text = '\n'.join(item.text.strip() for item in document.paragraphs if item.text.strip()).strip()
                elif ext == 'pptx':
                    try:
                        from pptx import Presentation
                    except ImportError as exc:
                        raise errors.RequestError(msg='解析 pptx 需要安装 python-pptx') from exc
                    presentation = Presentation(BytesIO(data))
                    texts: list[str] = []
                    for slide in presentation.slides:
                        for shape in slide.shapes:
                            text = getattr(shape, 'text', None)
                            if isinstance(text, str) and text.strip():
                                texts.append(text.strip())
                    text = '\n'.join(texts).strip()
                elif ext == 'xlsx':
                    try:
                        from openpyxl import load_workbook
                    except ImportError as exc:
                        raise errors.RequestError(msg='解析 xlsx 需要安装 openpyxl') from exc
                    workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
                    rows: list[str] = []
                    try:
                        for sheet in workbook.worksheets:
                            for row in sheet.iter_rows(values_only=True):
                                values = [str(item).strip() for item in row if item is not None and str(item).strip()]
                                if values:
                                    rows.append('\t'.join(values))
                    finally:
                        workbook.close()
                    text = '\n'.join(rows).strip()
                else:
                    raise errors.RequestError(msg='不支持的知识文件类型')
                if text:
                    segments.append(KnowledgeSegment(text=text))
        content = join_knowledge_text_segments(segments)
        if not content and not any(item.image for item in segments):
            raise errors.RequestError(msg='知识内容不能为空')
        document_title = resolved_title or Path(source).stem.strip()
        if not document_title:
            raise errors.RequestError(msg='知识标题不能为空')
        uploads.append(
            KnowledgeUpload(
                title=document_title,
                content=content,
                source=source,
                file_type=file_type,
                segments=tuple(segments),
            )
        )
    return uploads


def join_knowledge_text_segments(segments: Sequence[KnowledgeSegment]) -> str:
    """
    拼接无需 OCR 的文本片段和占位符

    :param segments: 解析片段
    :return:
    """
    parts: list[str] = []
    for segment in segments:
        if segment.text:
            parts.append(segment.text)
        elif segment.placeholder:
            parts.append(segment.placeholder)
    return '\n\n'.join(parts).strip()


def _extract_pdf_segments(data: bytes) -> list[KnowledgeSegment]:  # ruff: ignore[complex-structure]
    """
    从 PDF 页面提取文档知识片段

    :param data: PDF 文件字节
    :return:
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise errors.RequestError(msg='解析 PDF 需要安装 pypdf') from exc
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pdfium = None
    reader = PdfReader(BytesIO(data))
    segments: list[KnowledgeSegment] = []
    document = None
    try:
        for index, page in enumerate(reader.pages):
            text = (page.extract_text() or '').strip()
            if text:
                segments.append(KnowledgeSegment(text=text))
                continue
            image: bytes | None = None
            if pdfium is not None:
                with suppress(Exception):
                    if document is None:
                        document = pdfium.PdfDocument(data)
                    if 0 <= index < len(document):
                        bitmap = document[index].render(scale=2)
                        buffer = BytesIO()
                        bitmap.to_pil().save(buffer, format='PNG')
                        image = buffer.getvalue()
            if not image:
                image = next(
                    (
                        payload
                        for item in getattr(page, 'images', None) or []
                        if isinstance(payload := getattr(item, 'data', None), bytes) and payload
                    ),
                    None,
                )
            if image is not None:
                segments.append(KnowledgeSegment(image=image, media_type='image/png'))
    finally:
        if document is not None:
            document.close()
    return segments
