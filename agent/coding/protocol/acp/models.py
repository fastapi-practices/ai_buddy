from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.plugin.ai_buddy.enums import AIBuddyAcpRunnerName, AIBuddyAcpToolParseMode

_DEFAULT_STDIO_BUFFER_LIMIT_BYTES = 50 * 1024 * 1024

_BUILTIN_RUNNERS: dict[AIBuddyAcpRunnerName, dict[str, Any]] = {
    AIBuddyAcpRunnerName.opencode: {
        'command': 'opencode',
        'args': ['acp'],
        'trusted': True,
        'tool_parse_mode': AIBuddyAcpToolParseMode.update_detail,
    },
    AIBuddyAcpRunnerName.codebuddy: {
        'command': 'codebuddy',
        'args': ['--acp'],
        'trusted': True,
        'tool_parse_mode': AIBuddyAcpToolParseMode.update_detail,
    },
    AIBuddyAcpRunnerName.claude_code: {
        'command': 'npx',
        'args': ['-y', '@zed-industries/claude-agent-acp'],
        'trusted': True,
        'tool_parse_mode': AIBuddyAcpToolParseMode.update_detail,
    },
    AIBuddyAcpRunnerName.codex: {
        'command': 'npx',
        'args': ['-y', '@zed-industries/codex-acp'],
        'trusted': True,
        'tool_parse_mode': AIBuddyAcpToolParseMode.call_detail,
    },
    AIBuddyAcpRunnerName.kimi_code: {
        'command': 'kimi',
        'args': ['acp'],
        'trusted': True,
        'tool_parse_mode': AIBuddyAcpToolParseMode.update_detail,
    },
    AIBuddyAcpRunnerName.cursor_cli: {
        'command': 'agent',
        'args': ['acp'],
        'trusted': True,
        'tool_parse_mode': AIBuddyAcpToolParseMode.update_detail,
    },
    AIBuddyAcpRunnerName.pi: {
        'command': 'npx',
        'args': ['-y', 'pi-acp'],
        'trusted': True,
        'tool_parse_mode': AIBuddyAcpToolParseMode.update_detail,
    },
}


class ACPError(Exception):
    """ACP 运行错误"""

    def __init__(self, message: str, *, runner: str | None = None) -> None:
        """
        记录 ACP 错误及执行器名称

        :param message: ACP 错误消息
        :param runner: ACP 执行器名称
        :return:
        """
        super().__init__(message)
        self.runner = runner


@dataclass
class ACPRunnerConfig:
    """外部 ACP runner 启动规格"""

    enabled: bool = False
    command: str = ''
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    trusted: bool = False
    tool_parse_mode: AIBuddyAcpToolParseMode = AIBuddyAcpToolParseMode.update_detail
    stdio_buffer_limit_bytes: int = _DEFAULT_STDIO_BUFFER_LIMIT_BYTES

    def to_dict(self) -> dict[str, Any]:
        """将 ACP 启动配置转换为字典"""
        return {
            'enabled': self.enabled,
            'command': self.command,
            'args': list(self.args),
            'env': dict(self.env),
            'trusted': self.trusted,
            'tool_parse_mode': AIBuddyAcpToolParseMode(self.tool_parse_mode).value,
            'stdio_buffer_limit_bytes': self.stdio_buffer_limit_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ACPRunnerConfig:
        """
        从字典恢复 ACP 启动配置

        :param data: ACP 启动配置字典
        :return:
        """
        mode = str(data.get('tool_parse_mode') or AIBuddyAcpToolParseMode.update_detail.value)
        try:
            tool_parse_mode = AIBuddyAcpToolParseMode(mode)
        except ValueError as exc:
            raise ValueError(f'无效的 tool_parse_mode: {mode!r}') from exc
        return cls(
            enabled=bool(data.get('enabled')),
            command=str(data.get('command') or ''),
            args=[str(item) for item in (data.get('args') or [])],
            env={str(key): str(value) for key, value in dict(data.get('env') or {}).items()},
            trusted=bool(data.get('trusted')),
            tool_parse_mode=tool_parse_mode,
            stdio_buffer_limit_bytes=int(data.get('stdio_buffer_limit_bytes') or _DEFAULT_STDIO_BUFFER_LIMIT_BYTES),
        )


def default_acp_runners(*, enabled: bool = True) -> dict[str, ACPRunnerConfig]:
    """
    内置 runner，无后台配置页时工具挂上即全部可用

    :param enabled: 是否启用
    :return:
    """
    out: dict[str, ACPRunnerConfig] = {}
    for name, spec in _BUILTIN_RUNNERS.items():
        out[name.value] = ACPRunnerConfig(
            enabled=enabled,
            command=str(spec['command']),
            args=list(spec['args']),
            trusted=bool(spec.get('trusted', False)),
            tool_parse_mode=spec.get('tool_parse_mode', AIBuddyAcpToolParseMode.update_detail),
        )
    return out


@dataclass
class ACPConfig:
    """当前编码轮可用的 ACP runner 集合"""

    runners: dict[str, ACPRunnerConfig] = field(default_factory=default_acp_runners)

    def enabled_runner_names(self) -> list[str]:
        """列出已启用的 ACP 执行器名称"""
        return sorted(name for name, cfg in self.runners.items() if cfg.enabled)


def build_acp_config(*, runner: str | None = None, launch: dict[str, Any] | None = None) -> ACPConfig:
    """
    将本轮选择与启动参数应用到独立的 runner 配置

    :param runner: 本轮选择的 ACP 执行器名称
    :param launch: 覆盖执行器的启动参数
    :return:
    """
    runners = default_acp_runners()
    if runner is not None:
        if runner not in runners:
            raise ValueError('未知的 ACP runner')
        runners = {runner: runners[runner]}
        if launch is not None:
            runners[runner].command = launch['command']
            runners[runner].args = list(launch['args'])
    elif launch is not None:
        raise ValueError('ACP 启动参数需要指定 runner 名称')
    return ACPConfig(runners=runners)


@dataclass
class SuspendedPermission:
    """外部 agent 挂起的权限请求"""

    payload: dict[str, Any]
    options: list[dict[str, Any]]
    runner: str
    tool_name: str
    tool_kind: str
    target: str | None = None
    action: str | None = None
    summary: str | None = None
    command: str | None = None
    paths: list[str] = field(default_factory=list)
    requires_user_confirmation: bool = True
