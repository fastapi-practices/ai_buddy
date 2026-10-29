from backend.common.enums import IntEnum, StrEnum


class AIBuddyAssistantCategory(StrEnum):
    """AI 助手固定分类"""

    efficiency = 'efficiency'
    writing = 'writing'
    translation = 'translation'
    career = 'career'
    development = 'development'
    education = 'education'
    lifestyle = 'lifestyle'
    product = 'product'
    legal = 'legal'
    finance = 'finance'


ASSISTANT_CATEGORY_META = (
    {'code': AIBuddyAssistantCategory.efficiency, 'name': '效率办公', 'sort': 1},
    {'code': AIBuddyAssistantCategory.writing, 'name': '写作创作', 'sort': 2},
    {'code': AIBuddyAssistantCategory.translation, 'name': '翻译语言', 'sort': 3},
    {'code': AIBuddyAssistantCategory.career, 'name': '职场求职', 'sort': 4},
    {'code': AIBuddyAssistantCategory.development, 'name': '编程开发', 'sort': 5},
    {'code': AIBuddyAssistantCategory.education, 'name': '学习教育', 'sort': 6},
    {'code': AIBuddyAssistantCategory.lifestyle, 'name': '生活兴趣', 'sort': 7},
    {'code': AIBuddyAssistantCategory.product, 'name': '产品运营', 'sort': 8},
    {'code': AIBuddyAssistantCategory.legal, 'name': '法律合规', 'sort': 9},
    {'code': AIBuddyAssistantCategory.finance, 'name': '金融财务', 'sort': 10},
)


class AIBuddyAssistantSortType(StrEnum):
    """AI 助手列表排序"""

    comprehensive = 'comprehensive'
    hottest = 'hottest'
    newest = 'newest'


class AIBuddyModelKind(StrEnum):
    """AI 模型类型"""

    chat = 'chat'
    embedding = 'embedding'
    image = 'image'


class AIBuddyModelModality(StrEnum):
    """模型输入模态"""

    text = 'text'
    image = 'image'
    audio = 'audio'
    video = 'video'
    pdf = 'pdf'


MODEL_INPUT_MODALITIES: dict[AIBuddyModelKind, frozenset[AIBuddyModelModality]] = {
    AIBuddyModelKind.chat: frozenset(AIBuddyModelModality),
    AIBuddyModelKind.embedding: frozenset({AIBuddyModelModality.text}),
    AIBuddyModelKind.image: frozenset({AIBuddyModelModality.text, AIBuddyModelModality.image}),
}


class AIBuddyKnowledgeFileType(StrEnum):
    """知识文档类型"""

    md = 'md'
    txt = 'txt'
    pdf = 'pdf'
    docx = 'docx'
    pptx = 'pptx'
    xlsx = 'xlsx'
    image = 'image'


class AIBuddyDocumentExtractBackend(StrEnum):
    """知识文档抽取后端"""

    native = 'native'
    markitdown = 'markitdown'
    unstructured = 'unstructured'
    mineru = 'mineru'
    open_mineru = 'open_mineru'
    doc2x = 'doc2x'
    mistral = 'mistral'


class AIBuddyOcrBackend(StrEnum):
    """知识 OCR 后端"""

    system = 'system'
    paddleocr = 'paddleocr'
    onnx = 'onnx'
    vision = 'vision'
    mistral = 'mistral'


class AIBuddyModelCapability(StrEnum):
    """AI 模型能力"""

    tools = 'tools'
    thinking = 'thinking'


class AIBuddyProviderType(IntEnum):
    """AI 供应商类型"""

    openai = 0
    anthropic = 1
    google = 2
    xai = 3
    openrouter = 4
    openai_responses = 5

    @property
    def label(self) -> str:
        """展示名称"""
        return {
            AIBuddyProviderType.openai: 'OpenAI',
            AIBuddyProviderType.anthropic: 'Anthropic',
            AIBuddyProviderType.google: 'Google',
            AIBuddyProviderType.xai: 'xAI',
            AIBuddyProviderType.openrouter: 'OpenRouter',
            AIBuddyProviderType.openai_responses: 'OpenAI Responses',
        }[self]

    @property
    def default_api_host(self) -> str:
        """默认接口地址"""
        return {
            AIBuddyProviderType.openai: 'https://api.openai.com',
            AIBuddyProviderType.anthropic: 'https://api.anthropic.com',
            AIBuddyProviderType.google: 'https://generativelanguage.googleapis.com',
            AIBuddyProviderType.xai: 'https://api.x.ai',
            AIBuddyProviderType.openrouter: 'https://openrouter.ai',
            AIBuddyProviderType.openai_responses: 'https://api.openai.com',
        }[self]

    @property
    def default_api_path(self) -> str:
        """默认接口路径"""
        return {
            AIBuddyProviderType.openai: '/v1',
            AIBuddyProviderType.anthropic: '',
            AIBuddyProviderType.google: '/v1beta',
            AIBuddyProviderType.xai: '/v1',
            AIBuddyProviderType.openrouter: '/api/v1',
            AIBuddyProviderType.openai_responses: '/v1',
        }[self]


class AIBuddyMcpType(IntEnum):
    """MCP 类型"""

    stdio = 0
    sse = 1
    streamable_http = 2


class AIBuddyChatAttachmentSourceType(StrEnum):
    """聊天附件来源类型"""

    url = 'url'
    base64 = 'base64'


class AIBuddyChatGenerationType(StrEnum):
    """聊天生成类型"""

    text = 'text'
    image = 'image'


class AIBuddyMessageStatus(StrEnum):
    """AI 消息状态"""

    pending = 'pending'
    success = 'success'
    error = 'error'
    interrupted = 'interrupted'
    timeout = 'timeout'


class AIBuddyWebSearchType(StrEnum):
    """网络搜索模式"""

    off = 'off'
    builtin = 'builtin'
    exa = 'exa'
    tavily = 'tavily'
    duckduckgo = 'duckduckgo'


class AIBuddyChatThinkingType(StrEnum):
    """聊天请求思考强度"""

    off = 'off'
    minimal = 'minimal'
    low = 'low'
    medium = 'medium'
    high = 'high'
    xhigh = 'xhigh'
    max = 'max'


class AIBuddyAgentMode(StrEnum):
    """同一对话内的运行模式"""

    chat = 'chat'
    work = 'work'
    coding = 'coding'


class AIBuddyPermissionMode(StrEnum):
    """Agent 权限模式"""

    ask = 'ask'
    auto = 'auto'
    full = 'full'


class AIBuddyOrigin(StrEnum):
    """对话与消息来源"""

    web = 'web'
    im = 'im'
    cron = 'cron'


class AIBuddyConversationSurface(StrEnum):
    """会话入口"""

    chat = 'chat'
    image = 'image'


class AIBuddyConversationView(StrEnum):
    """聊天会话列表视图"""

    chat = 'chat'
    work = 'work'
    coding = 'coding'


class AIBuddyChannelType(StrEnum):
    """IM 通道类型"""

    wechat = 'wechat'
    qq = 'qq'
    wecom = 'wecom'
    feishu = 'feishu'
    dingtalk = 'dingtalk'
    telegram = 'telegram'
    discord = 'discord'


class AIBuddyChannelQrcodeStatus(StrEnum):
    """通道扫码状态"""

    wait = 'wait'
    scanned = 'scanned'
    confirmed = 'confirmed'
    expired = 'expired'
    error = 'error'


class AIBuddyToolPolicy(StrEnum):
    """工具策略"""

    allow = 'allow'
    ask = 'ask'
    deny = 'deny'


class AIBuddySlashEntry(StrEnum):
    """斜杠指令入口"""

    web = 'web'
    im = 'im'


class AIBuddySlashCommand(StrEnum):
    """斜杠指令"""

    help = 'help'
    status = 'status'
    new = 'new'
    stop = 'stop'
    compact = 'compact'
    retry = 'retry'
    title = 'title'
    polish = 'polish'
    list = 'list'
    switch = 'switch'

    @property
    def description(self) -> str:
        """指令说明"""
        return {
            AIBuddySlashCommand.help: '列出当前入口可用指令',
            AIBuddySlashCommand.status: '是否在生成、当前模式、最近模型',
            AIBuddySlashCommand.new: '用当前助手/项目新开对话',
            AIBuddySlashCommand.stop: '停止本轮生成',
            AIBuddySlashCommand.compact: '立即压缩当前对话上下文',
            AIBuddySlashCommand.retry: '用上一条用户消息再跑一轮',
            AIBuddySlashCommand.title: '无参数则生成标题，有参数则写入',
            AIBuddySlashCommand.polish: '润色输入框草稿，不落历史',
            AIBuddySlashCommand.list: '最近对话',
            AIBuddySlashCommand.switch: '切到另一条对话',
        }[self]

    @property
    def entries(self) -> tuple[AIBuddySlashEntry, ...]:
        """可用入口"""
        if self is AIBuddySlashCommand.polish:
            return (AIBuddySlashEntry.web,)
        if self in {AIBuddySlashCommand.list, AIBuddySlashCommand.switch}:
            return (AIBuddySlashEntry.im,)
        return (AIBuddySlashEntry.web, AIBuddySlashEntry.im)


class AIBuddyMessageRole(StrEnum):
    """对话消息角色"""

    system = 'system'
    user = 'user'
    assistant = 'assistant'
    tool = 'tool'


class AIBuddyChatMessageType(StrEnum):
    """聊天消息类型"""

    normal = 'normal'
    error = 'error'
    incomplete = 'incomplete'
    suspended = 'suspended'
    interrupted = 'interrupted'


class AIBuddyWorkspaceRefKind(StrEnum):
    """聊天工作区引用类型"""

    knowledge = 'knowledge'
    skill = 'skill'
    artifact = 'artifact'


class AIBuddyArtifactKind(StrEnum):
    """产物类型：图片、视频、音频、文本、文档、其他"""

    image = 'image'
    video = 'video'
    audio = 'audio'
    text = 'text'
    document = 'document'
    other = 'other'


class AIBuddyArtifactStorageBackend(StrEnum):
    """产物存储后端"""

    local = 'local'
    s3 = 's3'
    sandbox = 'sandbox'


class AIBuddyConversationSource(StrEnum):
    """会话事实源"""

    cloud = 'cloud'
    local = 'local'


class AIBuddyConversationAuditAction(StrEnum):
    """会话审计动作"""

    export = 'export'
    import_ = 'import'
    delete = 'delete'
    sync = 'sync'
    migrate = 'migrate'


class AIBuddyObjectKind(StrEnum):
    """统一对象类型"""

    attachment = 'attachment'
    artifact = 'artifact'
    workspace_file = 'workspace_file'
    tool_output = 'tool_output'
    test_report = 'test_report'
    knowledge = 'knowledge'
    skill = 'skill'


class AIBuddyObjectLocation(StrEnum):
    """统一对象所在位置"""

    local = 'local'
    sandbox = 'sandbox'
    s3 = 's3'
    cache = 'cache'


class AIBuddyObjectState(StrEnum):
    """统一对象生命周期状态"""

    active = 'active'
    tombstoned = 'tombstoned'
    deleted = 'deleted'


class AIBuddyObjectAvailability(StrEnum):
    """统一对象回显可用性"""

    available = 'available'
    client_side = 'client_side'
    tombstoned = 'tombstoned'
    deleted = 'deleted'
    missing = 'missing'
    storage_unavailable = 'storage_unavailable'


class AIBuddyObjectAuditAction(StrEnum):
    """统一对象审计动作"""

    register = 'register'
    reference = 'reference'
    unreference = 'unreference'
    tombstone = 'tombstone'
    revive = 'revive'
    delete = 'delete'
    delete_failed = 'delete_failed'
    read = 'read'


class AIBuddyArtifactState(StrEnum):
    """产物状态"""

    working = 'working'
    ready = 'ready'
    archived = 'archived'
    deleted = 'deleted'


class AIBuddyWorkspaceBackend(StrEnum):
    """工作区后端"""

    local = 'local'
    cloud = 'cloud'
    sandbox = 'sandbox'


class AIBuddyWorkspaceState(StrEnum):
    """工作区状态"""

    provisioning = 'provisioning'
    ready = 'ready'
    active = 'active'
    archived = 'archived'
    error = 'error'
    deleted = 'deleted'


class AIBuddyWorkspaceFileState(StrEnum):
    """工作区文件状态"""

    working = 'working'
    ready = 'ready'
    active = 'active'
    archived = 'archived'
    error = 'error'
    deleted = 'deleted'


class AIBuddyFollowUpMode(StrEnum):
    """跟进请求处理方式"""

    queue = 'queue'
    steer = 'steer'


class AIBuddyFollowUpStatus(StrEnum):
    """跟进请求状态"""

    queued = 'queued'
    dispatched = 'dispatched'
    steered = 'steered'
    failed = 'failed'


class AIBuddyApprovalStatus(StrEnum):
    """工具审批状态"""

    pending = 'pending'
    approved = 'approved'
    denied = 'denied'
    cancelled = 'cancelled'
    expired = 'expired'


class AIBuddyExecutionBackend(StrEnum):
    """编码助手执行后端，local 为桌面本机，sandbox 为服务端沙箱，具体沙箱服务商见 AIBuddySandboxProvider"""

    local = 'local'
    sandbox = 'sandbox'


class AIBuddySandboxProvider(StrEnum):
    """服务端沙箱服务商，均实现 Pydantic AI 的 Workspace 抽象，可随时切换"""

    opensandbox = 'opensandbox'
    docker = 'docker'
    e2b = 'e2b'
    modal = 'modal'
    daytona = 'daytona'
    sprites = 'sprites'
    smol = 'smol'
    boxlite = 'boxlite'


class AIBuddyExecutionCapability(StrEnum):
    """桌面执行协议能力"""

    run_tests_v1 = 'run_tests_v1'
    workspace_git_v1 = 'workspace_git_v1'
    input_files_v1 = 'input_files_v1'
    command_v1 = 'command_v1'


class AIBuddyExecutionMethod(StrEnum):
    """桌面执行协议方法"""

    stop = 'stop'
    list_files = 'list_files'
    read_file = 'read_file'
    write_file = 'write_file'
    write_input_file = 'write_input_file'
    edit_file = 'edit_file'
    run_bash = 'run_bash'
    run_command = 'run_command'
    run_tests = 'run_tests'
    git_status = 'git_status'
    git_diff = 'git_diff'
    run_background = 'run_background'
    get_endpoint = 'get_endpoint'


class AIBuddyAcpRunnerName(StrEnum):
    """本地 ACP Agent 名称"""

    opencode = 'opencode'
    codebuddy = 'codebuddy'
    claude_code = 'claude_code'
    codex = 'codex'
    kimi_code = 'kimi_code'
    cursor_cli = 'cursor_cli'
    pi = 'pi'


class AIBuddyInputQuestionKind(StrEnum):
    """结构化问题作答方式"""

    text = 'text'
    single = 'single'
    multiple = 'multiple'


class AIBuddyCommandReason(StrEnum):
    """测试命令执行完成或中止原因"""

    completed = 'completed'
    cancelled = 'cancelled'
    deadline = 'deadline'
    output_limit = 'output-limit'
    execution_error = 'execution-error'
    connection_error = 'connection-error'


class AIBuddyTestReportArchiveStatus(StrEnum):
    """测试报告归档状态"""

    saved = 'saved'
    failed = 'failed'


class AIBuddyEmbeddingBackend(StrEnum):
    """知识向量嵌入后端"""

    remote = 'remote'
    onnx = 'onnx'


class AIBuddyInputRequestKind(StrEnum):
    """用户输入请求类型"""

    questions = 'questions'
    secret = 'secret'


class AIBuddyInputRequestStatus(StrEnum):
    """用户输入请求状态"""

    pending = 'pending'
    answered = 'answered'
    cancelled = 'cancelled'


class AIBuddyAcpToolParseMode(StrEnum):
    """ACP 工具调用解析模式"""

    call_title = 'call_title'
    update_detail = 'update_detail'
    call_detail = 'call_detail'
