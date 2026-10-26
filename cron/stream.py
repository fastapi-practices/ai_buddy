import codecs
import json

from ag_ui.core import EventType
from starlette.responses import StreamingResponse

from backend.common.exception import errors


def _frame_error(frame: str) -> str | None:
    """
    提取 AG-UI 运行错误，忽略普通文本和工具事件

    :param frame: SSE 数据帧
    :return:
    """
    data = '\n'.join(line[5:].lstrip() for line in frame.splitlines() if line.startswith('data:'))
    if not data:
        return None
    try:
        event = json.loads(data)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    if event.get('type') == EventType.RUN_ERROR:
        return str(event.get('message') or '定时任务模型运行失败')
    return None


async def consume_cron_stream(response: StreamingResponse) -> None:
    """
    消费完整事件流后传播运行错误，避免把流内失败记录为成功

    :param response: 模型响应
    :return:
    """
    decoder = codecs.getincrementaldecoder('utf-8')()
    buffer = ''
    failure = None
    async for chunk in response.body_iterator:
        buffer += chunk if isinstance(chunk, str) else decoder.decode(bytes(chunk))
        buffer = buffer.replace('\r\n', '\n')
        while '\n\n' in buffer:
            frame, buffer = buffer.split('\n\n', 1)
            failure = failure or _frame_error(frame)
    buffer += decoder.decode(b'', final=True)
    failure = failure or _frame_error(buffer)
    if failure:
        raise errors.RequestError(msg=failure)
