import asyncio
import contextlib
import json

from time import monotonic

from acp.exceptions import RequestError as ACPRequestError

from backend.common.exception import errors
from backend.common.log import log
from backend.plugin.ai_buddy.agent.coding.protocol.acp.bridge import get_bridge, get_bridge_exit_code
from backend.plugin.ai_buddy.agent.coding.protocol.acp.models import ACPError, build_acp_config
from backend.plugin.ai_buddy.agent.coding.protocol.acp.service import ACPService
from backend.plugin.ai_buddy.schema.acp import CheckAIBuddyAcpParam, GetAIBuddyAcpCheckDetail


class AIBuddyAcpService:
    """检测桌面端用户本机的 ACP Agent"""

    @staticmethod
    async def check(*, user_id: int, runner: str, obj: CheckAIBuddyAcpParam) -> GetAIBuddyAcpCheckDetail:
        """
        检测用户本机 Agent 的 ACP 握手和会话初始化

        :param user_id: 用户 ID
        :param runner: 本地 Agent 名称
        :param obj: 检测参数
        :return:
        """
        record = await get_bridge(bridge_id=obj.bridge_id, user_id=user_id, runner=runner)
        started = monotonic()
        service = ACPService(
            config=build_acp_config(runner=runner),
            bridge_id=obj.bridge_id,
            user_id=user_id,
            cwd=record['cwd'],
            permission_mode=obj.permission_mode,
        )
        available = False
        code = 'agent_error'
        message = 'ACP 连接失败'

        try:
            async with asyncio.timeout(60):
                await service.check_connection(thread_id=obj.bridge_id, runner=runner)
                available = True
                code = 'ok'
                message = '本地 ACP 握手与会话初始化成功'
        except Exception as exc:
            exit_code = None
            with contextlib.suppress(Exception):
                exit_code = await get_bridge_exit_code(obj.bridge_id)
            if isinstance(exc, ACPRequestError):
                code, message = {
                    -32000: ('auth_required', '本地 Agent 尚未登录，请在本机终端完成登录后重新连接'),
                    -32601: ('unsupported', '本地程序不支持所需的 ACP 会话方法，请检查启动命令和参数'),
                    -32602: ('invalid_workspace', 'Agent 拒绝创建会话，请检查本地工作目录是否存在且可访问'),
                }.get(exc.code, ('agent_error', 'Agent 初始化会话失败，请检查本机 Agent 日志'))
            elif isinstance(exc, ACPError) and str(exc).startswith('ACP 协议版本不兼容'):
                code, message = 'protocol_mismatch', str(exc)
            elif isinstance(exc, (json.JSONDecodeError, ValueError)):
                code = 'invalid_response'
                message = 'Agent 返回了无效的 ACP 消息，请确认命令进入 ACP 模式且标准输出没有普通日志'
            elif exit_code is not None:
                code = 'agent_exited'
                message = f'本地 Agent 提前退出（退出码 {exit_code}），请检查安装、启动参数和本机日志'
            elif isinstance(exc, errors.ConflictError):
                code, message = 'already_used', '本地 ACP 桥接已被使用，检测或开始聊天前请重新建立连接'
            elif isinstance(exc, errors.RequestError):
                code, message = 'connection_lost', '本地 ACP 桥接已断开，请在桌面端重新连接'
            elif isinstance(exc, TimeoutError):
                code = 'timeout'
                message = 'ACP 检测超时，请检查本地 Agent 是否启动，以及命令是否需要下载或交互确认'
            elif isinstance(exc, (ConnectionError, OSError, EOFError)):
                code, message = 'connection_lost', '桌面端与本地 Agent 的连接已断开，请重新连接'
            else:
                code, message = 'agent_error', 'ACP 握手或会话初始化失败，请检查本机 Agent 日志和登录状态'
            log.warning('ACP check failed for runner %s: %s', runner, exc, exc_info=True)
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(service.close_all_sessions(), timeout=6)

        return GetAIBuddyAcpCheckDetail(
            available=available, code=code, message=message, latency_ms=round((monotonic() - started) * 1000)
        )


ai_buddy_acp_service: AIBuddyAcpService = AIBuddyAcpService()
