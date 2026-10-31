from collections.abc import Sequence

from office_oxide import Document
from pydantic_ai.messages import BinaryContent, ModelMessage, ModelRequest, UserPromptPart

_OFFICE_FORMATS = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    'application/msword': 'doc',
    'application/vnd.ms-excel': 'xls',
    'application/vnd.ms-powerpoint': 'ppt',
}


def is_office_media_type(media_type: str) -> bool:
    """
    判断是否为 Word、Excel、PowerPoint 文件，包含旧版格式

    :param media_type: 媒体类型
    :return:
    """
    return media_type in _OFFICE_FORMATS


def office_to_markdown(data: bytes, media_type: str) -> str:
    """
    把 Office 文件转换为保留标题、表格和备注的 Markdown，解析失败时抛出异常

    :param data: 文件内容
    :param media_type: 媒体类型
    :return:
    """
    with Document.from_bytes(data, _OFFICE_FORMATS[media_type]) as document:
        return document.to_markdown()


def input_attachments(messages: Sequence[ModelMessage]) -> list[BinaryContent]:
    """
    按出现顺序返回用户消息中的全部二进制附件

    :param messages: 模型消息列表
    :return:
    """
    return [
        item
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and not isinstance(part.content, str)
        for item in part.content
        if isinstance(item, BinaryContent)
    ]
