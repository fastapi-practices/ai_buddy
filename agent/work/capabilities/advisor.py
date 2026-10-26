from pydantic_ai.native_tools import AdvisorTool
from pydantic_ai_harness.advisor import Advisor
from pydantic_ai_harness.trajectory_judge import TrajectoryJudge

from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.models import auxiliary_model_name, bind_auxiliary_model
from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed, native_builtin_allowed
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType


async def build_advisor_capability(ctx: CapabilityContext) -> list[CapabilityResult]:
    """
    构建顾问能力，并在启用时用同一模型挂 TrajectoryJudge 中途纠偏

    :param ctx: 能力构建上下文
    :return:
    """
    advisor_model = (ctx.forwarded_props.advisor_model or '').strip()
    if not advisor_model:
        return []
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return []

    advisor_name = auxiliary_model_name(ctx, advisor_model)
    use_native = (
        native_builtin_allowed(adapter=ctx.adapter)
        and AdvisorTool in ctx.supported_native_tools
        and ctx.model is not None
        and ctx.model.system in {'anthropic', 'openrouter'}
    )
    if not use_native and not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        raise errors.RequestError(msg='当前模型不支持顾问工具，请更换模型或关闭顾问')
    bound_model = await bind_auxiliary_model(ctx, advisor_name)
    results = [
        CapabilityResult(
            capability=Advisor(
                f'{ctx.model.system}:{advisor_name}' if use_native else bound_model,
                mode='native' if use_native else 'local',
                forward_history=True,
            ),
            introduces_builtin_tool=use_native,
            introduces_function_tool_source=not use_native,
        )
    ]
    if ctx.model is not None:
        results.append(CapabilityResult(capability=TrajectoryJudge(model=ctx.model)))
    return results
