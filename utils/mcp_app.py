from typing import Any

from mcp.client.extension import ClientExtension

_MCP_UI_EXTENSION = {'io.modelcontextprotocol/ui': {'mimeTypes': ['text/html;profile=mcp-app']}}


class UiExtension(ClientExtension):
    """MCP 交互界面扩展能力声明"""

    identifier = 'io.modelcontextprotocol/ui'

    @classmethod
    def settings(cls) -> dict[str, Any]:
        """声明交互界面支持的媒体类型"""
        return _MCP_UI_EXTENSION[cls.identifier]


def ui_resource_uri(metadata: object) -> str | None:
    """
    只接受 MCP 工具声明的交互资源

    :param metadata: 连接元数据
    :return:
    """
    if not isinstance(metadata, dict):
        return None
    ui = metadata.get('ui')
    uri = ui.get('resourceUri') if isinstance(ui, dict) else None
    return uri if isinstance(uri, str) and uri.startswith('ui://') else None
