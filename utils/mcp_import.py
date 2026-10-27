import json
import re

from typing import Any

from backend.common.exception import errors
from backend.plugin.ai_buddy.enums import AIBuddyMcpType
from backend.plugin.ai_buddy.schema.mcp import CreateAIBuddyMcpParam

_SKIPPED_TYPES = frozenset({'inmemory'})


# 在导入入口统一兼容配置形态、传输类型和字段校验
def parse_mcp_servers_json(raw: str, *, allow_stdio: bool) -> list[CreateAIBuddyMcpParam]:  # ruff: ignore[complex-structure]
    """
    解析 Claude Desktop / Cursor 标准 mcpServers JSON

    :param raw: JSON 文本
    :param allow_stdio: 是否允许 stdio
    :return:
    """
    trimmed = (raw or '').strip()
    if not trimmed:
        raise errors.RequestError(msg='请粘贴 MCP JSON 配置')
    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError as exc:
        raise errors.RequestError(msg='MCP JSON 格式无效') from exc
    if not isinstance(parsed, dict):
        raise errors.RequestError(msg='MCP JSON 必须是对象')
    if isinstance(parsed.get('mcpServers'), dict):
        server_map = parsed['mcpServers']
    elif isinstance(parsed.get('servers'), dict):
        server_map = parsed['servers']
    elif _is_server_config(parsed):
        name = parsed.get('name')
        key = name.strip() if isinstance(name, str) and name.strip() else 'imported'
        server_map = {key: parsed}
    elif parsed and all(_is_server_config(value) for value in parsed.values()):
        server_map = parsed
    else:
        raise errors.RequestError(msg='未识别到标准 MCP 配置，请使用 mcpServers 格式')
    payloads: list[CreateAIBuddyMcpParam] = []
    for key, value in server_map.items():
        if not isinstance(value, dict):
            raise errors.RequestError(msg=f'{key} 配置必须是对象')
        if _normalize_type(value.get('type')) in _SKIPPED_TYPES:
            continue
        name = _pick_string(value.get('name')) or key.strip()
        if not name:
            raise errors.RequestError(msg='MCP 名称不能为空')
        command = _pick_string(value.get('command'))
        url = _pick_string(value.get('url')) or _pick_string(value.get('baseUrl')) or ''
        raw_type = value.get('type')
        normalized = _normalize_type(raw_type)
        if raw_type in (0, 1, 2):
            mcp_type = AIBuddyMcpType(raw_type)
        elif normalized == 'stdio':
            mcp_type = AIBuddyMcpType.stdio
        elif normalized == 'sse':
            mcp_type = AIBuddyMcpType.sse
        elif normalized in {'http', 'streamablehttp'}:
            mcp_type = AIBuddyMcpType.streamable_http
        elif normalized:
            raise errors.RequestError(msg=f'{name} 使用了不支持的类型 {raw_type}')
        elif command:
            mcp_type = AIBuddyMcpType.stdio
        elif url:
            mcp_type = (
                AIBuddyMcpType.sse
                if re.search(r'/sse(\b|/|$)', url, flags=re.IGNORECASE)
                else AIBuddyMcpType.streamable_http
            )
        else:
            raise errors.RequestError(msg=f'{name} 缺少 command 或 url')
        is_stdio = mcp_type == AIBuddyMcpType.stdio
        if is_stdio and not allow_stdio:
            raise errors.AuthorizationError(msg=f'{name} 为 stdio 类型，仅超级管理员可以使用')
        if is_stdio and not command:
            raise errors.RequestError(msg=f'{name} 缺少 command')
        if not is_stdio and not url:
            raise errors.RequestError(msg=f'{name} 缺少 url')
        args = None
        raw_args = value.get('args')
        if is_stdio and raw_args:
            if isinstance(raw_args, list):
                args = [str(item).strip() for item in raw_args if str(item).strip()] or None
            elif isinstance(raw_args, str):
                args = raw_args.strip().split() or None
            else:
                raise errors.RequestError(msg=f'{name} 的 args 必须是数组或字符串')
        payloads.append(
            CreateAIBuddyMcpParam(
                name=name,
                type=mcp_type,
                description=_pick_string(value.get('description')),
                command=command if is_stdio else None,
                args=args,
                env=_to_object(value.get('env'), '环境变量', name) if is_stdio else None,
                url=None if is_stdio else url,
                headers=None if is_stdio else _to_object(value.get('headers'), '请求头', name),
                timeout=_to_number(value.get('timeout'), 5),
                read_timeout=_to_number(value.get('read_timeout') or value.get('readTimeout'), 300),
                tool_prefix=_pick_string(value.get('tool_prefix') or value.get('toolPrefix')),
                include_instructions=value.get('include_instructions') is True
                or value.get('includeInstructions') is True,
            )
        )
    if not payloads:
        raise errors.RequestError(msg='未解析到可导入的 MCP 服务')
    return payloads


def _normalize_type(value: object) -> str:
    """
    规范化 MCP 服务传输类型

    :param value: 传输类型配置值
    :return:
    """
    if not isinstance(value, str):
        return ''
    return re.sub(r'[\s_-]', '', value.strip().lower())


def _is_server_config(value: object) -> bool:
    """
    判断配置项是否为 MCP 服务配置

    :param value: MCP 配置项
    :return:
    """
    if not isinstance(value, dict):
        return False
    command = value.get('command')
    if isinstance(command, str) and command.strip():
        return True
    url = value.get('url')
    if isinstance(url, str) and url.strip():
        return True
    base_url = value.get('baseUrl')
    if isinstance(base_url, str) and base_url.strip():
        return True
    raw_type = value.get('type')
    return raw_type in (0, 1, 2) or _normalize_type(raw_type) in {'stdio', 'sse', 'http', 'streamablehttp'}


def _pick_string(value: object) -> str | None:
    """
    从 MCP 配置中提取字符串字段

    :param value: MCP 配置值
    :return:
    """
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _to_object(value: object, field: str, name: str) -> dict[str, Any] | None:
    """
    将 MCP 配置字段转换为对象

    :param value: MCP 配置值
    :param field: 字段定义
    :param name: 技能名称
    :return:
    """
    if value is None or not value:
        return None
    if not isinstance(value, dict):
        raise errors.RequestError(msg=f'{name} 的 {field} 必须是 JSON 对象')
    return value


def _to_number(value: object, fallback: float) -> float:
    """
    将 MCP 配置字段转换为数值

    :param value: MCP 配置值
    :param fallback: 默认值
    :return:
    """
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int | float) and value >= 0:
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = float(value)
        except ValueError:
            return fallback
        if parsed >= 0:
            return parsed
    return fallback
