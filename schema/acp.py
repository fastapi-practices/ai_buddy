from pathlib import PurePosixPath, PureWindowsPath

from pydantic import Field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyAcpRunnerName, AIBuddyPermissionMode


class CheckAIBuddyAcpParam(SchemaBase):
    """ACP 可用性检测参数"""

    bridge_id: str = Field(pattern=r'^[a-f0-9]{32}$', description='桌面端建立的本地连接 ID')
    permission_mode: AIBuddyPermissionMode = Field(AIBuddyPermissionMode.ask, description='本地 Agent 操作审批模式')


class GetAIBuddyAcpCheckDetail(SchemaBase):
    """ACP 握手检测结果，不包含模型额度验证"""

    available: bool = Field(description='是否完成协议握手与会话初始化')
    message: str = Field(description='检测结果说明')
    code: str = Field(default='ok', description='检测结果分类，供客户端区分安装、登录、协议和连接故障')
    latency_ms: int = Field(description='检测耗时，毫秒')


class CreateAIBuddyAcpBridgeParam(SchemaBase):
    """桌面端提供的本地 Agent 连接信息"""

    runner: AIBuddyAcpRunnerName = Field(description='本地 Agent 名称')
    cwd: str = Field(description='桌面端固定的本地绝对工作目录')

    @field_validator('cwd')
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        """
        校验本地工作目录的绝对路径格式

        :param value: 工作目录
        :return:
        """
        if '\0' in value or not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()):
            raise ValueError('本地工作目录必须是绝对路径')
        return value


class GetAIBuddyAcpBridgeDetail(SchemaBase):
    """桌面端一次性 ACP 连接凭证"""

    bridge_id: str = Field(description='一次性本地连接 ID')
    ticket: str = Field(description='WebSocket 一次性连接凭证')
