from dataclasses import dataclass

from pydantic_ai import CapabilityEvent, RunContext
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai_harness.compaction import (
    ClearToolResults,
    CompactionStrategy,
    DeduplicateFileReads,
    RelevanceCompaction,
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
    estimate_token_count,
)

from backend.core.conf import settings
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType


@dataclass(kw_only=True)
class BuddyCompactionCompleted(
    CapabilityEvent,
    namespace='buddy_compaction',
    name='completed',
):
    """实际压缩完成后的数量变化"""

    messages_before: int
    messages_after: int
    tokens_before: int
    tokens_after: int


class ObservableTieredCompaction(TieredCompaction[ChatAgentDeps]):
    """在原生压缩确实改变上下文后通知客户端"""

    async def before_model_request(
        self, ctx: RunContext[ChatAgentDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        """
        压缩上下文后发送消息和 token 数变化事件

        :param ctx: 运行上下文
        :param request_context: 请求上下文
        :return:
        """
        count = len(ctx.messages)
        tokens = estimate_token_count(ctx.messages, self.tokenizer)
        result = await super().before_model_request(ctx, request_context)
        next_tokens = estimate_token_count(ctx.messages, self.tokenizer)
        if count != len(ctx.messages) or tokens != next_tokens:
            await ctx.emit(
                BuddyCompactionCompleted(
                    messages_before=count,
                    messages_after=len(ctx.messages),
                    tokens_before=tokens,
                    tokens_after=next_tokens,
                )
            )
        return result


def _workspace_read_key(call: ToolCallPart) -> str | None:
    """
    将知识和产物读取映射为去重键

    :param call: 模型工具调用
    :return:
    """
    args = call.args_as_dict()
    if call.tool_name == 'get_knowledge':
        knowledge_id = args.get('knowledge_id')
        return None if knowledge_id is None else f'knowledge:{knowledge_id}'
    if call.tool_name == 'get_artifact':
        artifact_id = args.get('artifact_id')
        return None if artifact_id is None else f'artifact:{artifact_id}'
    return None


def build_compaction_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    先清工具结果和重复读取，必要时再滑动窗口或摘要

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    if ctx.forwarded_props.compaction_enabled is False:
        return CapabilityResult(capability=None)

    keep_messages = ctx.forwarded_props.compaction_keep_messages or settings.AI_BUDDY_COMPACTION_KEEP_MESSAGES
    max_messages = ctx.forwarded_props.compaction_max_messages or settings.AI_BUDDY_COMPACTION_MAX_MESSAGES
    if ctx.forwarded_props.compaction_strategy == 'relevance':
        return CapabilityResult(
            capability=ObservableTieredCompaction(
                tiers=[
                    RelevanceCompaction(
                        model=ctx.model,
                        max_tokens=1,
                        context_window=ctx.context_window,
                        target_fraction=0.7,
                        judge_concurrency=2,
                    )
                ],
                target_fraction=0.85,
                context_window=ctx.context_window,
            )
        )
    tiers: list[CompactionStrategy] = [
        ClearToolResults(max_tokens=1, keep_pairs=4),
        DeduplicateFileReads(file_key=_workspace_read_key),
        SlidingWindowCompaction(
            max_messages=max_messages,
            keep_messages=keep_messages,
        ),
        SummarizingCompaction(model=ctx.model, max_tokens=1, keep_messages=keep_messages),
    ]
    return CapabilityResult(
        capability=ObservableTieredCompaction(
            tiers=tiers,
            target_fraction=0.85,
            context_window=ctx.context_window,
        )
    )
