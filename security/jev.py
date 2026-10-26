import json

from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.typesafe import TypeSafeModel
from pydantic_ai.providers.typesafe import TypeSafeProvider
from pydantic_ai_harness.guardrails import GuardrailResult, InputGuardrail, ToolCallInfo, ToolGuardrail

from backend.common.log import log
from backend.core.conf import settings
from backend.plugin.ai_buddy.security.tool_policy import is_mcp_tool

_JEV_TOOL_RISK = frozenset({
    'write',
    'edit',
    'bash',
    'bash_background',
    'run_tests',
    'write_artifact',
    'write_memory',
    'run_code',
    'web_fetch',
    'acp_runner',
    'delegate_task',
})


class JevInputVerdict(BaseModel):
    """办公助手用户提示的安全判定"""

    harmful: float = Field(
        ge=0,
        le=1,
        description=(
            'Probability that this prompt asks an office work assistant to destroy data, leak secrets, '
            'jailbreak safety, attack systems, or produce criminal content.'
        ),
    )


class JevToolVerdict(BaseModel):
    """办公助手工具调用的处置判定"""

    action: Literal['run', 'reject', 'ask'] = Field(
        description='Run the tool, reject it, or pause for a human before it runs.',
    )


@lru_cache(maxsize=4)
def _build_jev_agent(kind: Literal['input', 'tool'], api_key: str, model: str) -> Agent[None, Any]:
    """
    按类型、密钥和模型缓存 Jev 判定 Agent，配置变化后自动重建

    :param kind: 判定类型
    :param api_key: TypeSafe 密钥
    :param model: Jev 模型
    :return:
    """
    return Agent(
        TypeSafeModel(model, provider=TypeSafeProvider(api_key=api_key)),
        output_type=JevInputVerdict if kind == 'input' else JevToolVerdict,
        name=f'ai_buddy_jev_{kind}',
    )


def _jev_agent(kind: Literal['input', 'tool']) -> Agent[None, Any]:
    return _build_jev_agent(
        kind,
        str(settings.AI_BUDDY_TYPESAFE_API_KEY or '').strip(),
        str(settings.AI_BUDDY_JEV_MODEL or '').strip() or 'jev-latest',
    )


def jev_enabled() -> bool:
    """是否已配置 TypeSafe 密钥并启用 Jev 护栏"""
    return bool(str(settings.AI_BUDDY_TYPESAFE_API_KEY or '').strip())


def is_jev_tool_risk(name: str) -> bool:
    """
    判断工具是否需要 Jev 语义检查

    :param name: 工具名称
    :return:
    """
    return name in _JEV_TOOL_RISK or name.startswith('mcp_')


def build_jev_capabilities(*, allow_ask: bool) -> list[InputGuardrail | ToolGuardrail]:
    """
    构建可挂到 Agent 的 Jev 输入和工具护栏

    :param allow_ask: 工具判定为 ask 时是否交给人工确认
    :return:
    """
    if not jev_enabled():
        return []
    return [
        InputGuardrail(guard=jev_input_ok),
        ToolGuardrail(guard=jev_tool_decide_for_run if allow_ask else _jev_tool_decide_strict_for_run),
    ]


async def jev_input_ok(prompt: str) -> GuardrailResult:
    """
    用 Jev 判定用户提示是否应进入模型

    :param prompt: 用户提示
    :return:
    """
    try:
        agent = _jev_agent('input')
        result = await agent.run(prompt)
    except Exception as exc:
        log.warning(f'Jev 输入检查失败，放行: {exc}')
        return GuardrailResult.allow()
    if result.output.harmful >= settings.AI_BUDDY_JEV_INPUT_THRESHOLD:
        return GuardrailResult.block('请求被安全策略拒绝')
    return GuardrailResult.allow()


async def jev_tool_decide_for_run(ctx: RunContext[Any], call: ToolCallInfo) -> GuardrailResult:
    """
    从当前工具定义读取 MCP 来源，不依赖用户配置的前缀

    :param ctx: 模型运行上下文
    :param call: 工具调用信息
    :return:
    """
    tool_def = ctx.tools.get(call.name)
    if tool_def is not None and is_mcp_tool(tool_def):
        return await _jev_tool_verdict(call)
    if is_jev_tool_risk(call.name):
        return await _jev_tool_verdict(call)
    return GuardrailResult.allow()


async def _jev_tool_verdict(call: ToolCallInfo) -> GuardrailResult:
    state = json.dumps({'tool': call.name, 'args': _jsonable(call.args)}, ensure_ascii=False)
    try:
        agent = _jev_agent('tool')
        result = await agent.run(state)
    except Exception as exc:
        log.warning(f'Jev 工具检查失败，改为人工确认: {exc}')
        return GuardrailResult.approve()
    match result.output.action:
        case 'run':
            return GuardrailResult.allow()
        case 'reject':
            return GuardrailResult.block(f'工具调用被安全策略拒绝: {call.name}')
        case 'ask':
            return GuardrailResult.approve()


async def _jev_tool_decide_strict_for_run(ctx: RunContext[Any], call: ToolCallInfo) -> GuardrailResult:
    """
    按工具来源判定风险，子代理和编码宿主拒绝人工确认请求

    :param ctx: 模型运行上下文
    :param call: 工具调用信息
    :return:
    """
    result = await jev_tool_decide_for_run(ctx, call)
    if result.action == 'approve':
        return GuardrailResult.block(result.message or f'工具调用需要人工确认: {call.name}')
    return result


def _jsonable(value: object) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
