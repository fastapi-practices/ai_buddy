# AI Buddy

提供对话、工作、编码与生图能力，支持 MCP、知识库、技能和 IM 通道，由后端运行 AI 服务，管理后台维护全站资源，客户端承载用户操作

本插件与基础 `ai` 插件互斥，不要同时安装

## 插件类型

- 应用级插件

## 配置说明

在 `backend/.env` 中添加以下内容：

```env
# [ Plugin ] ai_buddy
AI_BUDDY_QDRANT_URL='http://127.0.0.1:6333'
AI_BUDDY_QDRANT_API_KEY=''
AI_BUDDY_OPENSANDBOX_DOMAIN='127.0.0.1:8090'
AI_BUDDY_OPENSANDBOX_API_KEY='ai-buddy-opensandbox-local'
AI_BUDDY_OPENSANDBOX_PROTOCOL='http'
AI_BUDDY_EXA_API_KEY=''
AI_BUDDY_TAVILY_API_KEY=''
AI_BUDDY_TYPESAFE_API_KEY=''
AI_BUDDY_UNSTRUCTURED_API_KEY=''
AI_BUDDY_MARKITDOWN_DOCINTEL_ENDPOINT=''
AI_BUDDY_MARKITDOWN_DOCINTEL_API_KEY=''
AI_BUDDY_MINERU_API_KEY=''
AI_BUDDY_OPEN_MINERU_API_URL=''
AI_BUDDY_OPEN_MINERU_API_KEY=''
AI_BUDDY_DOC2X_API_KEY=''
AI_BUDDY_MISTRAL_API_KEY=''
AI_BUDDY_PADDLEOCR_API_URL=''
```

插件目录下 `plugin.toml` 的 `[settings]` 中包含以下内容：

```toml
[settings]
AI_BUDDY_COMPACTION_KEEP_MESSAGES = 40
AI_BUDDY_COMPACTION_MAX_MESSAGES = 80
AI_BUDDY_HTTP_MAX_RETRIES = 5
AI_BUDDY_MCP_MAX_RETRIES = 1
AI_BUDDY_DOCUMENT_EXTRACT_BACKEND = "native"
AI_BUDDY_UNSTRUCTURED_API_URL = "https://api.unstructuredapp.io/general/v0/general"
AI_BUDDY_DOC2X_API_URL = "https://v2.doc2x.noedgeai.com"
AI_BUDDY_MISTRAL_API_URL = "https://api.mistral.ai"
AI_BUDDY_EMBEDDING_BACKEND = "remote"
AI_BUDDY_ONNX_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
AI_BUDDY_OCR_BACKEND = "system"
AI_BUDDY_RAG_CHUNK_CHARS = 500
AI_BUDDY_RAG_CHUNK_OVERLAP = 80
AI_BUDDY_RAG_TOP_K = 6
AI_BUDDY_QDRANT_COLLECTION = "ai_buddy_knowledge"
AI_BUDDY_AGENT_INSTRUMENTATION_ENABLED = false
AI_BUDDY_AGENT_INCLUDE_TOOL_RETURN_SCHEMAS = false
AI_BUDDY_AGENT_THREAD_EXECUTOR_MAX_WORKERS = 8
AI_BUDDY_AGENT_STEP_PERSISTENCE_ENABLED = false
AI_BUDDY_AGENT_RUN_TIMEOUT_SECONDS = 3600
AI_BUDDY_AGENT_TOOL_TIMEOUT_SECONDS = 600
AI_BUDDY_AGENT_RETRIES = 1
AI_BUDDY_OBJECT_GC_GRACE_HOURS = 24
AI_BUDDY_OBJECT_GC_INTERVAL_SECONDS = 0
AI_BUDDY_ATTACHMENT_MAX_BYTES = 20971520
AI_BUDDY_AGENT_BASH_TIMEOUT_SECONDS = 30
AI_BUDDY_AGENT_MAX_FILE_BYTES = 1000000
AI_BUDDY_AGENT_EXECUTION_BACKEND = "local"
AI_BUDDY_AGENT_SANDBOX_PROVIDER = "opensandbox"
AI_BUDDY_AGENT_SANDBOX_IMAGE = "fba-ai-buddy-sandbox:latest"
AI_BUDDY_AGENT_SANDBOX_CPU = "1"
AI_BUDDY_AGENT_SANDBOX_MEMORY = "2Gi"
AI_BUDDY_AGENT_SANDBOX_TIMEOUT_MINUTES = 30
AI_BUDDY_WORKSPACE_GC_GRACE_HOURS = 24
AI_BUDDY_MCP_OAUTH_REDIRECT_URI = ""
AI_BUDDY_QDRANT_MEMORY_COLLECTION = "ai_buddy_memory"
AI_BUDDY_JEV_MODEL = "jev-latest"
AI_BUDDY_JEV_INPUT_THRESHOLD = 0.75
```

在 `backend/core/conf.py` 中添加以下内容：

```python
##################################################
# [ Plugin ] ai_buddy
##################################################
# .env
AI_BUDDY_QDRANT_URL: str = 'http://127.0.0.1:6333'
AI_BUDDY_QDRANT_API_KEY: str = ''
AI_BUDDY_OPENSANDBOX_DOMAIN: str = '127.0.0.1:8090'
AI_BUDDY_OPENSANDBOX_API_KEY: str = 'ai-buddy-opensandbox-local'
AI_BUDDY_OPENSANDBOX_PROTOCOL: str = 'http'
AI_BUDDY_EXA_API_KEY: str = ''
AI_BUDDY_TAVILY_API_KEY: str = ''
AI_BUDDY_TYPESAFE_API_KEY: str = ''
AI_BUDDY_UNSTRUCTURED_API_KEY: str = ''
AI_BUDDY_MARKITDOWN_DOCINTEL_ENDPOINT: str = ''
AI_BUDDY_MARKITDOWN_DOCINTEL_API_KEY: str = ''
AI_BUDDY_MINERU_API_KEY: str = ''
AI_BUDDY_OPEN_MINERU_API_URL: str = ''
AI_BUDDY_OPEN_MINERU_API_KEY: str = ''
AI_BUDDY_DOC2X_API_KEY: str = ''
AI_BUDDY_MISTRAL_API_KEY: str = ''
AI_BUDDY_PADDLEOCR_API_URL: str = ''

# 基础配置（in plugin.toml）
AI_BUDDY_COMPACTION_KEEP_MESSAGES: int = 40
AI_BUDDY_COMPACTION_MAX_MESSAGES: int = 80
AI_BUDDY_HTTP_MAX_RETRIES: int = 5
AI_BUDDY_MCP_MAX_RETRIES: int = 1
AI_BUDDY_DOCUMENT_EXTRACT_BACKEND: Literal[
    'native', 'markitdown', 'unstructured', 'mineru', 'open_mineru', 'doc2x', 'mistral'
] = 'native'
AI_BUDDY_UNSTRUCTURED_API_URL: str = 'https://api.unstructuredapp.io/general/v0/general'
AI_BUDDY_DOC2X_API_URL: str = 'https://v2.doc2x.noedgeai.com'
AI_BUDDY_MISTRAL_API_URL: str = 'https://api.mistral.ai'
AI_BUDDY_EMBEDDING_BACKEND: Literal['remote', 'onnx'] = 'remote'
AI_BUDDY_ONNX_EMBEDDING_MODEL: str = 'BAAI/bge-small-zh-v1.5'
AI_BUDDY_OCR_BACKEND: Literal['system', 'paddleocr', 'onnx', 'vision', 'mistral'] = 'system'
AI_BUDDY_RAG_CHUNK_CHARS: int = 500
AI_BUDDY_RAG_CHUNK_OVERLAP: int = 80
AI_BUDDY_RAG_TOP_K: int = 6
AI_BUDDY_QDRANT_COLLECTION: str = 'ai_buddy_knowledge'
AI_BUDDY_AGENT_INSTRUMENTATION_ENABLED: bool = False
AI_BUDDY_AGENT_INCLUDE_TOOL_RETURN_SCHEMAS: bool = False
AI_BUDDY_AGENT_THREAD_EXECUTOR_MAX_WORKERS: int = 8
AI_BUDDY_AGENT_STEP_PERSISTENCE_ENABLED: bool = False
AI_BUDDY_AGENT_RUN_TIMEOUT_SECONDS: int = 3600
AI_BUDDY_AGENT_TOOL_TIMEOUT_SECONDS: int = 600
AI_BUDDY_AGENT_RETRIES: int = 1
AI_BUDDY_OBJECT_GC_GRACE_HOURS: int = 24
AI_BUDDY_OBJECT_GC_INTERVAL_SECONDS: int = 0
AI_BUDDY_ATTACHMENT_MAX_BYTES: int = 20971520
AI_BUDDY_AGENT_BASH_TIMEOUT_SECONDS: int = 30
AI_BUDDY_AGENT_MAX_FILE_BYTES: int = 1000000
AI_BUDDY_AGENT_EXECUTION_BACKEND: Literal['local', 'sandbox'] = 'local'
AI_BUDDY_AGENT_SANDBOX_PROVIDER: Literal[
    'opensandbox', 'docker', 'e2b', 'modal', 'daytona', 'sprites', 'smol', 'boxlite'
] = 'opensandbox'
AI_BUDDY_AGENT_SANDBOX_IMAGE: str = 'fba-ai-buddy-sandbox:latest'
AI_BUDDY_AGENT_SANDBOX_CPU: str = '1'
AI_BUDDY_AGENT_SANDBOX_MEMORY: str = '2Gi'
AI_BUDDY_AGENT_SANDBOX_TIMEOUT_MINUTES: int = 30
AI_BUDDY_WORKSPACE_GC_GRACE_HOURS: int = 24
AI_BUDDY_MCP_OAUTH_REDIRECT_URI: str = ''
AI_BUDDY_QDRANT_MEMORY_COLLECTION: str = 'ai_buddy_memory'
AI_BUDDY_JEV_MODEL: str = 'jev-latest'
AI_BUDDY_JEV_INPUT_THRESHOLD: float = 0.75
```

## 配置项说明

- `AI_BUDDY_COMPACTION_KEEP_MESSAGES`：控制压缩后保留的最近消息数
- `AI_BUDDY_COMPACTION_MAX_MESSAGES`：控制触发历史压缩的消息数阈值
- `AI_BUDDY_HTTP_MAX_RETRIES`：控制模型供应商 HTTP 请求的最大重试次数
- `AI_BUDDY_MCP_MAX_RETRIES`：控制 MCP 工具调用的最大重试次数
- `AI_BUDDY_DOCUMENT_EXTRACT_BACKEND`：控制知识文档抽取后端
- `AI_BUDDY_UNSTRUCTURED_API_URL`：控制 Unstructured API 地址
- `AI_BUDDY_DOC2X_API_URL`：控制 Doc2X API 地址
- `AI_BUDDY_MISTRAL_API_URL`：控制 Mistral API 地址
- `AI_BUDDY_EMBEDDING_BACKEND`：控制知识库未指定模型时的向量化方式
- `AI_BUDDY_ONNX_EMBEDDING_MODEL`：控制 RAG 默认使用的本地 ONNX 向量模型
- `AI_BUDDY_OCR_BACKEND`：控制知识 OCR 后端
- `AI_BUDDY_RAG_CHUNK_CHARS`：控制知识切片的字符长度
- `AI_BUDDY_RAG_CHUNK_OVERLAP`：控制相邻知识切片的重叠字符数
- `AI_BUDDY_RAG_TOP_K`：控制知识语义检索返回的条数
- `AI_BUDDY_QDRANT_COLLECTION`：控制知识向量写入的 Qdrant 集合名称
- `AI_BUDDY_AGENT_INSTRUMENTATION_ENABLED`：控制是否用 Pydantic AI 原生 OTel 追踪 Agent、模型请求和工具调用
- `AI_BUDDY_AGENT_INCLUDE_TOOL_RETURN_SCHEMAS`：控制是否把工具返回结构告知模型
- `AI_BUDDY_AGENT_THREAD_EXECUTOR_MAX_WORKERS`：控制同步工具共享线程池的最大线程数
- `AI_BUDDY_AGENT_STEP_PERSISTENCE_ENABLED`：控制是否持久化每步快照、事件和工具副作用台账
- `AI_BUDDY_AGENT_RUN_TIMEOUT_SECONDS`：控制单次运行的默认时限，客户端传入的执行时限不能超过它
- `AI_BUDDY_AGENT_TOOL_TIMEOUT_SECONDS`：控制单次工具调用的时限
- `AI_BUDDY_AGENT_RETRIES`：控制 Agent 层的工具与输出校验重试次数，网络重试只由 `AI_BUDDY_HTTP_MAX_RETRIES` 负责，两层互不叠加
- `AI_BUDDY_OBJECT_GC_GRACE_HOURS`：控制统一对象失去全部引用后，墓碑保留多久才允许物理删除
- `AI_BUDDY_OBJECT_GC_INTERVAL_SECONDS`：控制后台物理回收无引用对象的间隔秒数，0 表示关闭，只能手动回收
- `AI_BUDDY_ATTACHMENT_MAX_BYTES`：控制暂存附件（上传或远程下载）的字节数上限
- `AI_BUDDY_AGENT_BASH_TIMEOUT_SECONDS`：控制工作区命令的执行超时
- `AI_BUDDY_AGENT_MAX_FILE_BYTES`：控制工作区单文件读写大小上限
- `AI_BUDDY_AGENT_EXECUTION_BACKEND`：控制客户端未显式选择执行后端时的默认值，`local` 为桌面本机，`sandbox` 为服务端沙箱
- `AI_BUDDY_AGENT_SANDBOX_PROVIDER`：控制服务端沙箱的默认服务商，客户端可通过 `sandboxProvider` 在受支持的服务商中切换，除 `opensandbox` 外的服务商需安装对应扩展，如 `uv add "pydantic-ai-harness[e2b]"`
- `AI_BUDDY_AGENT_SANDBOX_IMAGE`：控制新建沙箱使用的镜像或模板，E2B 为模板名，Daytona 为快照名，Sprites 不使用
- `AI_BUDDY_AGENT_SANDBOX_CPU`：控制 OpenSandbox 沙箱 CPU 限额，其他服务商不使用
- `AI_BUDDY_AGENT_SANDBOX_MEMORY`：控制 OpenSandbox 沙箱内存限额，其他服务商不使用
- `AI_BUDDY_AGENT_SANDBOX_TIMEOUT_MINUTES`：控制 OpenSandbox 沙箱存活时间，其他服务商由其自身的寿命与空闲策略决定
- `AI_BUDDY_WORKSPACE_GC_GRACE_HOURS`：控制工作区孤立对象清理前的最短保留时间
- `AI_BUDDY_MCP_OAUTH_REDIRECT_URI`：控制 MCP OAuth 授权回调地址
- `AI_BUDDY_QDRANT_MEMORY_COLLECTION`：控制记忆向量写入的 Qdrant 集合名称
- `AI_BUDDY_JEV_MODEL`：控制工作、编码、生图输入和高风险工具护栏使用的 Jev 模型
- `AI_BUDDY_JEV_INPUT_THRESHOLD`：控制 Jev 判定提示有害后拦截的概率阈值

## 使用方式

1. 安装并启用参数配置、S3 和 AI Buddy 插件，完成数据库初始化后重启后端服务
2. 安装配套前端插件，在后台配置默认 S3 存储、供应商、模型和默认模型，并维护系统内置资源
3. 在客户端选择模型和助手，发起对话或工作任务，管理个人 MCP、知识、技能与产物；通道绑定和对话定时也在客户端完成
4. 编码任务使用独立会话，选择桌面本机工作区或服务端沙箱；使用 ACP 外部助手前，先在本机安装并登录对应 Agent，再通过桌面连接
5. 运行机制、执行环境准备与远程部署见 [架构文档](架构.md)

## 卸载说明

- 停用相关通道与定时任务，卸载插件并移除相关环境变量和参数配置
- 清理配套前端与客户端集成，按保留需求处理存储数据和远程执行服务

## 联系方式

- 作者：`wu-clan`
- 反馈方式：提交 Issue 或 PR
