from collections.abc import Sequence
from dataclasses import replace

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart, repair_messages
from pydantic_ai_harness.compaction import ClearToolResults, SlidingWindowCompaction

from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.coding.attachments import coding_user_content


async def compact_coding_history(
    messages: Sequence[ModelMessage],
    *,
    enabled: bool | None = None,
    keep_messages: int | None = None,
    max_messages: int | None = None,
) -> list[ModelMessage]:
    """
    修复并按消息数量压缩编码历史

    :param messages: 持久化的供应商消息历史
    :param enabled: 是否启用压缩，空值沿用服务端配置
    :param keep_messages: 压缩后保留的消息数
    :param max_messages: 触发压缩的消息数
    :return:
    """
    history = repair_messages(messages)
    history = [
        replace(
            message,
            parts=[
                replace(part, content=coding_user_content(list(part.content), historical=True))
                if isinstance(part, UserPromptPart) and not isinstance(part.content, str)
                else part
                for part in message.parts
            ],
        )
        if isinstance(message, ModelRequest)
        else message
        for message in history
    ]
    if enabled is False:
        return history

    keep = settings.AI_BUDDY_COMPACTION_KEEP_MESSAGES if keep_messages is None else keep_messages
    maximum = settings.AI_BUDDY_COMPACTION_MAX_MESSAGES if max_messages is None else max_messages
    if len(history) <= maximum or keep < 1 or maximum < 1:
        return history

    clear_results = ClearToolResults(max_tokens=1, keep_pairs=4)
    history = await clear_results.compact(history, None)
    history = await SlidingWindowCompaction(max_messages=maximum, keep_messages=keep).compact(history, None)
    return repair_messages(history)
