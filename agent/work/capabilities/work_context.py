from pydantic_ai import InstructionPart
from pydantic_ai.capabilities import Capability

from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyChatGenerationType

_CHAT_CONSTRAINTS = (
    '当前是对话模式，围绕用户的问题进行解释、讨论、总结和轻量起草，直接回复有用的内容。'
    '可以根据需要使用联网搜索、资料检索和用户已选择的业务工具。'
    '不要自动启动任务规划、子代理或工具编排，不要主动保存或修改工作产物。'
    '需要持续执行多步任务、批量处理或保存产物时，提示用户切换工作模式。'
    '不要声称已经访问本机文件、修改仓库或执行 shell；这些操作需要编码模式。'
)

_WORK_CONSTRAINTS = (
    '不要把当前产品当成代码代理：当前是工作模式，以资料、文档、数据和产物为任务对象。'
    '优先使用技能、知识检索、产物写入，以及已连接的业务工具完成任务。'
    '需要计算、整理数据或批量调用工具时，可以使用已提供的 run_code；'
    '它是受限的工具编排环境，不提供项目磁盘工作区、shell 或任意第三方 Python 库。'
    '需要实际修改仓库、安装依赖或运行项目命令时，说明需要切换编码模式，不要声称已经执行。'
    '交付可使用的结果；需要保存时写入产物，并说明来源、实际完成的操作和未完成的限制。'
)
_DEFAULT_ROLE = '你是办公工作助手，负责调研、写作、规划、整理知识和产物。'


def build_work_context_instruction(ctx: CapabilityContext) -> str:
    """
    构建工作上下文指令

    :param ctx: 能力构建上下文
    :return:
    """
    chat = ctx.forwarded_props.agent_mode == AIBuddyAgentMode.chat
    parts = [_CHAT_CONSTRAINTS if chat else _WORK_CONSTRAINTS]
    if ctx.assistant_name:
        parts.append(f'当前助手：{ctx.assistant_name}')
    if ctx.assistant_prompt:
        parts.append(ctx.assistant_prompt)
    elif not ctx.assistant_name:
        parts.append('你是对话助手，帮助用户问答、讨论和起草内容。' if chat else _DEFAULT_ROLE)
    if ctx.project_name:
        parts.append(f'当前项目：{ctx.project_name}')
    if ctx.conversation_goal:
        parts.append(f'对话目标：{ctx.conversation_goal}')
    return '\n'.join(parts)


def build_work_context_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    注入产品约束、角色、项目和对话目标

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    return CapabilityResult(
        capability=Capability(
            id='work-context',
            description='产品约束与当前会话工作上下文',
            instructions=InstructionPart(build_work_context_instruction(ctx), on_change='append'),
        )
    )
