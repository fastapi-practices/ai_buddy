from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field, Tag, TypeAdapter, model_validator

from backend.common.exception import errors
from backend.plugin.ai_buddy.enums import (
    AIBuddyAcpRunnerName,
    AIBuddyAgentMode,
    AIBuddyChatGenerationType,
    AIBuddyChatThinkingType,
    AIBuddyConversationSurface,
    AIBuddyExecutionBackend,
    AIBuddyPermissionMode,
    AIBuddySandboxProvider,
    AIBuddyToolPolicy,
    AIBuddyWebSearchType,
    AIBuddyWorkspaceRefKind,
)
from backend.plugin.ai_buddy.schema.chat_base import AIBuddyChatSchemaBase, AIBuddyRunAgentInput
from backend.plugin.ai_buddy.schema.image import AIBuddyImageForwardedPropsParam
from backend.plugin.ai_buddy.schema.quote import AIBuddyMessageQuote
from backend.plugin.ai_buddy.utils.workspace import validate_workspace_id


class AIBuddyChatModelSelectParam(AIBuddyChatSchemaBase):
    """聊天模型选择参数"""

    provider_id: int = Field(description='供应商 ID')
    model_id: str = Field(description='模型 ID')


class AIBuddyChatThinkingParam(AIBuddyChatSchemaBase):
    """聊天模型思考参数"""

    thinking: AIBuddyChatThinkingType | None = Field(None, description='模型思考模式')


class AIBuddyChatWorkspaceRefParam(AIBuddyChatSchemaBase):
    """聊天工作区引用"""

    kind: AIBuddyWorkspaceRefKind = Field(description='引用类型')
    id: int = Field(description='引用记录 ID')


class AIBuddyChatRuntimeParam(AIBuddyChatSchemaBase):
    """聊天运行时控制参数"""

    mcp_ids: list[int] | None = Field(None, description='启用的 MCP ID 列表')
    mcp_approve_writes: bool = Field(default=False, description='MCP 工具默认询问')
    memory_enabled: bool | None = Field(default=True, description='是否启用跨会话记忆，空值沿用默认（开启）')
    tool_policies: dict[str, AIBuddyToolPolicy] | None = Field(None, description='本轮工具策略覆盖，allow/ask/deny')
    web_search: AIBuddyWebSearchType = Field(default=AIBuddyWebSearchType.off, description='网络搜索模式')
    workspace_ref: AIBuddyChatWorkspaceRefParam | None = Field(None, description='工作区引用')
    workspace_id: str | None = Field(None, max_length=128, description='编码工作区 ID')
    advisor_model: str | None = Field(None, description='顾问模型名称，空值表示不启用')
    file_understanding_model: str | None = Field(None, description='当前供应商下的文件理解模型，空值表示不启用')
    smart_search_model: str | None = Field(None, description='当前供应商下的代码语义搜索模型，仅内置编码模式生效')
    cache_enabled: bool = Field(default=True, description='是否启用 SDK 管理的提示词缓存')
    background_subagents_enabled: bool = Field(default=False, description='是否允许子代理在本轮后台执行')
    run_timeout: float | None = Field(
        None, gt=0, allow_inf_nan=False, description='整轮执行时限，包含工具与审批等待，单位秒'
    )
    compaction_enabled: bool | None = Field(None, description='是否启用对话压缩，空值沿用服务端默认（当前为开启）')
    compaction_strategy: Literal['summary', 'relevance'] = Field(
        default='summary', description='历史压缩策略：摘要或相关性筛选'
    )
    compaction_keep_messages: int | None = Field(None, ge=1, description='压缩时保留的最近消息数')
    compaction_max_messages: int | None = Field(None, ge=1, description='触发滑动窗口压缩的消息数上限')
    agent_mode: AIBuddyAgentMode = Field(
        default=AIBuddyAgentMode.work,
        description='本轮交互模式，chat 用于问答和讨论，work 执行资料与产物任务，coding 执行代码仓库任务',
    )
    permission_mode: AIBuddyPermissionMode = Field(
        default=AIBuddyPermissionMode.ask,
        description='编码模式权限，仅 agent_mode=coding 时生效',
    )
    acp_runner: bool | None = Field(None, description='编码轮是否挂 acp_runner，由客户端指定，空值表示不启用')
    acp_runner_name: AIBuddyAcpRunnerName | None = Field(None, description='本轮启用的 ACP runner 名，空则使用默认集合')

    acp_bridge_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$', description='桌面端本地 ACP 连接 ID')
    acp_imported_attachment_hashes: list[Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]] = Field(
        default_factory=list, max_length=32, description='桌面端已导入当前工作区的本轮附件 SHA-256'
    )
    execution_backend: AIBuddyExecutionBackend = Field(
        default=AIBuddyExecutionBackend.local,
        description=('工作与编码模式的工作位置，local 为在你的计算机上，sandbox 为服务端沙箱，首轮确定后不可更改'),
    )
    sandbox_provider: AIBuddySandboxProvider | None = Field(
        None,
        description=(
            '服务端沙箱服务商，仅 execution_backend=sandbox 时生效，不传使用服务端默认服务商，'
            '切换后旧沙箱会被销毁并重建，工作区文件不会迁移'
        ),
    )
    execution_bridge_id: str | None = Field(
        None, pattern=r'^[a-f0-9]{32}$', description='内置编码助手的桌面执行连接 ID，独立于 ACP 连接'
    )

    @model_validator(mode='after')
    def validate_workspace(self) -> 'AIBuddyChatRuntimeParam':
        """校验编码工作区标识"""
        if self.workspace_id is not None:
            try:
                self.workspace_id = validate_workspace_id(self.workspace_id.strip())
            except errors.RequestError as exc:
                raise ValueError(exc.msg) from exc
        return self

    @model_validator(mode='after')
    def validate_acp_config(self) -> 'AIBuddyChatRuntimeParam':
        """本地连接必须绑定到一个明确的 runner"""
        if self.acp_bridge_id is not None and self.acp_runner_name is None:
            raise ValueError('ACP 本地连接需要指定 runner 名称')
        return self


class AIBuddyChatModelSettingsParam(AIBuddyChatSchemaBase):
    """聊天模型采样参数"""

    max_tokens: int | None = Field(None, description='停止前最多可生成的 token 数')
    temperature: float | None = Field(None, description='模型生成文本的随机性')
    top_p: float | None = Field(None, description='模型生成文本的多样性')
    timeout: float | None = Field(None, description='覆盖客户端对请求的默认超时（单位：s）')
    request_timeout: float | None = Field(
        None, gt=0, allow_inf_nan=False, description='单次模型请求总时限，包含重试与流消费，单位秒'
    )
    seed: int | None = Field(None, description='用于模型的随机种子')
    presence_penalty: float | None = Field(None, description='根据新 token 是否出现在文本中来处罚')
    frequency_penalty: float | None = Field(None, description='根据新 token 目前在文本中的出现频率进行惩罚')
    logit_bias: dict[str, int] | None = Field(None, description='修改完成中出现指定标记的可能性')
    stop_sequences: list[str] | None = Field(None, description='这些序列会导致模型停止生成')
    extra_body: dict[str, Any] | None = Field(None, description='额外模型采样参数，仅合并当前供应商 settings 认识的键')


class AIBuddyChatOutputParam(AIBuddyChatSchemaBase):
    """聊天输出控制参数"""

    generation_type: Literal[AIBuddyChatGenerationType.text] = Field(
        default=AIBuddyChatGenerationType.text,
        description='生成类型',
    )


class AIBuddyChatForwardedPropsParam(
    AIBuddyChatModelSelectParam,
    AIBuddyChatThinkingParam,
    AIBuddyChatRuntimeParam,
    AIBuddyChatModelSettingsParam,
    AIBuddyChatOutputParam,
):
    """对话扩展参数"""

    assistant_id: int | None = Field(None, description='助手 ID，仅新建对话时生效')
    project_id: int | None = Field(None, gt=0, description='项目 ID，仅新建对话时生效')
    quote: AIBuddyMessageQuote | None = Field(None, description='本轮用户消息的引用定位锚点，业务扩展')


def _forwarded_props_tag(data: Any) -> str:
    """
    为 Pydantic 判别联合选择聊天或生图参数分支

    :param data: 客户端扩展参数或已解析模型
    :return:
    """
    if isinstance(data, dict):
        raw = data.get('generation_type', data.get('generationType', AIBuddyChatGenerationType.text))
    else:
        raw = getattr(data, 'generation_type', AIBuddyChatGenerationType.text)
    if raw in {AIBuddyChatGenerationType.image, AIBuddyChatGenerationType.image.value}:
        return AIBuddyChatGenerationType.image
    return AIBuddyChatGenerationType.text


AIBuddyForwardedPropsParam = Annotated[
    Annotated[AIBuddyChatForwardedPropsParam, Tag(AIBuddyChatGenerationType.text)]
    | Annotated[AIBuddyImageForwardedPropsParam, Tag(AIBuddyChatGenerationType.image)],
    Discriminator(_forwarded_props_tag),
]


def parse_forwarded_props(data: Any) -> AIBuddyForwardedPropsParam:
    """
    按 generation_type 解析对话或生图扩展参数

    :param data: 客户端 forwarded_props
    :return:
    """
    return TypeAdapter(AIBuddyForwardedPropsParam).validate_python(data)


def conversation_surface_of(forwarded_props: AIBuddyForwardedPropsParam) -> AIBuddyConversationSurface:
    """
    按生成类型解析会话入口

    :param forwarded_props: 扩展参数
    :return:
    """
    if isinstance(forwarded_props, AIBuddyImageForwardedPropsParam):
        return AIBuddyConversationSurface.image
    return AIBuddyConversationSurface.chat


class AIBuddyChatPolishParam(AIBuddyChatSchemaBase):
    """润色输入框草稿参数"""

    text: str = Field(description='输入框当前草稿')
    provider_id: int | None = Field(None, description='本轮选中的供应商 ID，空则用默认对话模型')
    model_id: str | None = Field(None, description='本轮选中的模型 ID，空则用默认对话模型')


class GetAIBuddyChatPolishDetail(AIBuddyChatSchemaBase):
    """润色输入框草稿结果"""

    text: str = Field(description='改写后的草稿，由客户端写回输入框')


class AIBuddyChatCompletionParam(AIBuddyRunAgentInput):
    """AG-UI 聊天运行请求"""

    forwarded_props: AIBuddyChatForwardedPropsParam = Field(description='聊天扩展参数')


class AIBuddyChatRegenerateParam(AIBuddyChatCompletionParam):
    """AG-UI 重生成请求，messages 中可携带替换后的用户消息"""
