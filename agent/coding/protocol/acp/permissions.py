import ntpath
import posixpath

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from backend.plugin.ai_buddy.agent.coding.protocol.acp.models import SuspendedPermission

BLOCKED_COMMAND_PATTERNS = (
    'rm -rf /',
    'sudo rm -rf',
    'mkfs',
    'dd if=',
)


def _permission_payload(option: Any) -> dict[str, Any] | None:
    """
    将 ACP 权限选项转换为字典

    :param option: ACP 权限选项
    :return:
    """
    if isinstance(option, dict):
        return dict(option)
    model_dump = getattr(option, 'model_dump', None)
    if callable(model_dump):
        data = model_dump(by_alias=True, exclude_none=True)
        if isinstance(data, dict):
            return data
    return None


def _tool_command(tool_call: dict[str, Any]) -> str | None:
    """
    从 ACP 工具调用中提取命令

    :param tool_call: ACP 工具调用信息
    :return:
    """
    raw_input = tool_call.get('rawInput')
    if isinstance(raw_input, dict):
        command = raw_input.get('command')
        if isinstance(command, str) and command.strip():
            return command.strip()
        argv = raw_input.get('args') or raw_input.get('argv')
        if isinstance(argv, list):
            parts = [str(item).strip() for item in argv if str(item).strip()]
            if parts:
                return ' '.join(parts)
    return None


def _tool_paths(tool_call: dict[str, Any]) -> list[str]:
    """
    提取 ACP 工具调用涉及的文件路径

    :param tool_call: ACP 工具调用信息
    :return:
    """
    paths: list[str] = []
    seen: set[str] = set()

    def add_path(value: Any) -> None:
        """
        收集去重后的非空工具路径

        :param value: 待收集的路径值
        :return:
        """
        if not isinstance(value, str):
            return
        text = value.strip()
        if not text or text in seen:
            return
        seen.add(text)
        paths.append(text)

    for location in tool_call.get('locations') or []:
        if isinstance(location, dict):
            add_path(location.get('path'))
    for content in tool_call.get('content') or []:
        if isinstance(content, dict) and content.get('type') == 'diff':
            add_path(content.get('path'))
    raw_input = tool_call.get('rawInput')
    if isinstance(raw_input, dict):
        add_path(raw_input.get('path'))
    return paths[:5]


class ACPPermissionAdapter:
    """把 ACP 权限请求收成 Buddy 可审批的结构"""

    def __init__(self, cwd: str) -> None:
        """
        按客户端平台设置权限路径规则

        :param cwd: 当前执行目录
        :return:
        """
        self.cwd = cwd
        self._paths = ntpath if PureWindowsPath(cwd).drive else posixpath

    def build_suspended_permission(
        self,
        *,
        runner: str,
        tool_call: Any,
        options: list[Any],
    ) -> SuspendedPermission:
        """
        组装等待用户选择的 ACP 权限请求

        :param runner: ACP 执行器名称
        :param tool_call: ACP 工具调用信息
        :param options: ACP 提供的权限选项
        :return:
        """
        tool_call_payload = _permission_payload(tool_call) or {}
        title = tool_call_payload.get('title')
        summary = title.strip() if isinstance(title, str) and title.strip() else None
        raw_kind = tool_call_payload.get('kind')
        kind = raw_kind.strip().lower() if isinstance(raw_kind, str) and raw_kind.strip() else None
        command = _tool_command(tool_call_payload)
        paths = _tool_paths(tool_call_payload)
        target = command or summary
        if len(paths) > 1:
            target = f'{len(paths)} files'
        elif paths:
            target = paths[0]
            try:
                path_type = PureWindowsPath if self._paths is ntpath else PurePosixPath
                path = path_type(target)
                if path.is_absolute():
                    try:
                        target = str(path.relative_to(path_type(self.cwd)))
                    except ValueError:
                        target = str(path)
            except (OSError, RuntimeError, ValueError):
                target = paths[0]
        option_payloads: list[dict[str, Any]] = []
        for option in options:
            payload = _permission_payload(option)
            if payload is not None:
                option_payloads.append(payload)
        return SuspendedPermission(
            payload={'toolCall': tool_call_payload, 'options': option_payloads},
            options=option_payloads,
            runner=runner,
            tool_name=summary or 'external-agent',
            tool_kind=kind or 'other',
            target=target,
            action=kind,
            summary=summary,
            command=command,
            paths=paths,
            requires_user_confirmation=True,
        )

    @staticmethod
    def resolve_option_by_id(options: list[Any], option_id: str) -> dict[str, Any] | None:
        """
        按精确选项 ID 查找权限选项

        :param options: ACP 权限选项
        :param option_id: 待查找的权限选项 ID
        :return:
        """
        key = option_id.strip()
        if not key:
            return None
        for opt in options:
            if not isinstance(opt, dict):
                continue
            candidate = str(opt.get('optionId') or '').strip()
            if candidate == key:
                return opt
        return None

    @staticmethod
    def preferred_allow_option(options: list[Any]) -> dict[str, Any] | None:
        """
        优先选择单次授权并忽略拒绝选项

        :param options: ACP 权限选项
        :return:
        """
        payloads = [item for item in (_permission_payload(opt) for opt in options) if item is not None]
        for kind in ('allow_once', 'allow_always'):
            for opt in payloads:
                if opt.get('kind') == kind and opt.get('optionId'):
                    return opt
        return None

    def selected_response(self, option: dict[str, Any] | None) -> Any:
        """
        构建 ACP 已选择权限选项的响应

        :param option: 用户选择的权限选项
        :return:
        """
        from acp.schema import AllowedOutcome, RequestPermissionResponse

        if option is None:
            return self.cancelled_response()
        option_id = str(option['optionId'])
        return RequestPermissionResponse(outcome=AllowedOutcome(option_id=option_id, outcome='selected'))

    @staticmethod
    def cancelled_response() -> Any:
        """构建 ACP 权限请求取消响应"""
        from acp.schema import DeniedOutcome, RequestPermissionResponse

        return RequestPermissionResponse(outcome=DeniedOutcome(outcome='cancelled'))

    def is_hard_blocked(self, tool_call: Any) -> bool:
        """
        检查命令或路径是否触发强制阻止规则

        :param tool_call: ACP 工具调用信息
        :return:
        """
        payload = _permission_payload(tool_call) or {}
        command = str(_tool_command(payload) or '').lower()
        if any(pattern in command for pattern in BLOCKED_COMMAND_PATTERNS):
            return True
        for path_value in _tool_paths(payload):
            candidate = self._paths.normcase(self._paths.normpath(self._paths.join(self.cwd, path_value)))
            cwd = self._paths.normcase(self._paths.normpath(self.cwd))
            try:
                if self._paths.commonpath([candidate, cwd]) != cwd:
                    return True
            except ValueError:
                return True
        return False
