from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyExecutionBackend, AIBuddyExecutionCapability, AIBuddyPermissionMode

AIBuddyDesktopExecutionBackend = Literal[AIBuddyExecutionBackend.local]


class GetAIBuddyExecutionOptionsDetail(SchemaBase):
    """客户端默认执行配置，不包含远程凭据或本机目录"""

    default_backend: AIBuddyExecutionBackend = Field(description='未设置客户端执行后端时的默认值')
    capabilities: list[AIBuddyExecutionCapability] = Field(
        default_factory=list, description='服务端支持的可协商执行能力'
    )


class CreateAIBuddyExecutionBridgeParam(SchemaBase):
    """桌面端执行连接参数，不接收服务器启动命令"""

    model_config = ConfigDict(extra='forbid')

    backend: AIBuddyDesktopExecutionBackend = Field(description='桌面本机 OS 沙箱执行后端')
    cwd: str = Field(min_length=1, max_length=4096, description='桌面端固定的绝对工作目录')
    permission_mode: AIBuddyPermissionMode = Field(AIBuddyPermissionMode.ask, description='本次连接的操作审批模式')
    capabilities: list[AIBuddyExecutionCapability] = Field(description='客户端支持且已协商的全部执行能力')

    @field_validator('capabilities')
    @classmethod
    def validate_capabilities(cls, value: list[AIBuddyExecutionCapability]) -> list[AIBuddyExecutionCapability]:
        """
        桌面连接必须实现当前执行协议的全部能力

        :param value: 客户端能力列表
        :return:
        """
        if set(value) != set(AIBuddyExecutionCapability):
            raise ValueError('桌面连接必须声明当前执行协议的全部能力')
        return value

    @field_validator('cwd')
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        """
        工作目录由桌面端校验存在性，服务器只校验路径格式

        :param value: 待处理值
        :return:
        """
        if any(char in value for char in ('\0', '\n', '\r')) or not (
            PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()
        ):
            raise ValueError('桌面工作目录必须是有效的绝对路径')
        return value


class GetAIBuddyExecutionBridgeDetail(SchemaBase):
    """一次性执行连接凭证"""

    bridge_id: str = Field(description='一次性桌面执行连接 ID')
    ticket: str = Field(description='WebSocket 一次性连接凭证')


class AIBuddyExecutionError(SchemaBase):
    """桌面端执行错误"""

    model_config = ConfigDict(extra='forbid', strict=True)

    code: str = Field(min_length=1, max_length=64, description='执行错误分类')
    message: str = Field(min_length=1, max_length=4096, description='执行错误说明')


class AIBuddyExecutionResponse(SchemaBase):
    """桌面端 RPC 响应"""

    model_config = ConfigDict(extra='forbid', strict=True)

    id: str = Field(pattern=r'^[a-f0-9]{32}$', description='对应 RPC 请求 ID')
    result: Any = Field(description='成功结果，空操作或错误时为 null')
    error: AIBuddyExecutionError | None = Field(description='成功时为 null，否则包含错误分类和说明')

    @model_validator(mode='after')
    def validate_outcome(self) -> 'AIBuddyExecutionResponse':
        """执行结果和错误不能同时出现"""
        if self.error is not None and self.result is not None:
            raise ValueError('执行错误响应不能同时包含成功结果')
        return self


class AIBuddyExecutionFileEntry(SchemaBase):
    """桌面工作区目录项"""

    model_config = ConfigDict(extra='forbid', strict=True)

    path: str = Field(description='相对工作区的路径')
    is_dir: bool = Field(description='是否为目录')
    size: int | None = Field(ge=0, description='文件字节数，目录为 null')
