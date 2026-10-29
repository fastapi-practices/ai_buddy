import hashlib
import mimetypes
import re

from pydantic_ai.messages import BinaryContent, UserContent

from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.coding.types import AgentRunContext


def input_attachment_path(attachment: BinaryContent) -> str:
    """
    为用户输入生成内容寻址路径，客户端文件名不能改变写入目录

    :param attachment: 已解码用户附件
    :return:
    """
    if len(attachment.data) > 10 * 1024 * 1024:
        raise errors.RequestError(msg='附件超过 10 MiB 工作区导入上限')
    digest = hashlib.sha256(attachment.data).hexdigest()
    suffix = mimetypes.guess_extension(attachment.media_type) or '.bin'
    name = re.sub(r'[^a-zA-Z0-9._-]', '_', attachment.identifier or f'input{suffix}')[:120]
    if not name or not name[0].isalnum():
        name = f'input_{name}'[:120]
    return f'inbound/{digest}-{name}'


async def import_input_attachment(ctx: AgentRunContext, attachment_id: int) -> str:
    """
    按编号把本轮附件原始字节导入工作区

    :param ctx: 编码运行上下文
    :param attachment_id: 本轮附件编号
    :return:
    """
    if ctx.sandbox is None:
        raise errors.RequestError(msg='当前运行没有可写工作区')
    if type(attachment_id) is not int or not 1 <= attachment_id <= len(ctx.input_attachments):
        raise errors.RequestError(msg='附件编号无效')
    attachment = ctx.input_attachments[attachment_id - 1]
    return await ctx.sandbox.write_input_file(path=input_attachment_path(attachment), content=attachment.data)


def coding_user_content(
    content: list[UserContent], *, can_import: bool = True, historical: bool = False
) -> list[UserContent]:
    """
    保留模型原生媒体，普通文件通过元数据和附件导入工具处理

    :param content: 本轮用户输入
    :param can_import: 是否具有工作区导入工具
    :param historical: 是否来自已持久化的历史输入
    :return:
    """
    result: list[UserContent] = []
    index = 0
    for item in content:
        if not isinstance(item, BinaryContent):
            result.append(item)
            continue
        index += 1
        if historical:
            delivery = '这是历史附件，编号不属于本轮 import_attachment；若此前已导入，请按工具结果中的实际路径读取'
        elif can_import:
            path = input_attachment_path(item)
            delivery = (
                f'可调用 import_attachment(attachment_id={index}) 保存到 {path} 后使用文件工具读取；尚未写入工作区'
            )
        else:
            delivery = '调用 acp_runner 时按外部 Agent 声明的附件能力发送；本机导入路径以用户消息附带的路径为准'
        result.append(
            f'用户附件 #{index}：{item.identifier}，类型 {item.media_type}，{len(item.data)} 字节。{delivery}'
        )
        if item.media_type.startswith('text/') or item.media_type in {'application/json', 'application/xml'}:
            try:
                text = item.data.decode('utf-8')
            except UnicodeDecodeError:
                continue
            result.append(f'附件 #{index} 的文本预览（最多 12000 字符）：\n{text[:12000]}')
        elif item.is_image or item.is_audio or item.is_video or item.media_type == 'application/pdf':
            result.append(item)
    return result
