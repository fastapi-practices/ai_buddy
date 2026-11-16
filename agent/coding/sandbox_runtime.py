from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.exceptions import SandboxApiException, SandboxException
from opensandbox.manager import SandboxManager
from opensandbox.models.filesystem import WriteEntry
from opensandbox.models.sandboxes import NetworkPolicy

from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.coding.execution_bridge import get_bridge, open_bridge
from backend.plugin.ai_buddy.agent.coding.sandbox import (
    LIVE_SANDBOXES,
    WORKSPACE_ROOT,
    CodingSandbox,
    DesktopBridgeWorkspace,
    OpenSandboxWorkspace,
    get_live_sandbox,
)
from backend.plugin.ai_buddy.crud.crud_sandbox_workspace import ai_buddy_sandbox_workspace_dao
from backend.plugin.ai_buddy.enums import AIBuddyExecutionBackend, AIBuddyPermissionMode
from backend.plugin.ai_buddy.model.sandbox_workspace import AIBuddySandboxWorkspace
from backend.plugin.ai_buddy.utils.workspace import validate_workspace_id


def sandbox_unavailable_reason() -> str | None:
    """返回服务端沙箱不可用原因，已配置 OpenSandbox 服务地址时为空"""
    if settings.AI_BUDDY_OPENSANDBOX_DOMAIN.strip():
        return None
    return '未配置 OpenSandbox 服务地址'


def has_server_sandbox() -> bool:
    """判断服务端是否已配置可用的 OpenSandbox"""
    return sandbox_unavailable_reason() is None


def _connection_config() -> ConnectionConfig:
    """构建 OpenSandbox 连接配置"""
    domain = settings.AI_BUDDY_OPENSANDBOX_DOMAIN.strip()
    if not domain:
        raise errors.RequestError(msg='未配置 OpenSandbox 服务地址')
    return ConnectionConfig(
        domain=domain,
        api_key=settings.AI_BUDDY_OPENSANDBOX_API_KEY.strip() or None,
        protocol=settings.AI_BUDDY_OPENSANDBOX_PROTOCOL,
        use_server_proxy=True,
    )


async def _attach_opensandbox(
    record: AIBuddySandboxWorkspace, *, conversation_id: str, user_id: int, permission_mode: AIBuddyPermissionMode
) -> OpenSandboxWorkspace | None:
    """
    接回 OpenSandbox 实例，已暂停则恢复并续期，实例已不存在返回空

    :param record: 沙箱登记
    :param conversation_id: 对话 ID
    :param user_id: 用户 ID
    :param permission_mode: 权限模式
    :return:
    """
    config = _connection_config()
    manager = await SandboxManager.create(connection_config=config)
    try:
        info = await manager.get_sandbox_info(record.sandbox_ref)
    except SandboxApiException as exc:
        if exc.status_code == 404:
            return None
        raise
    finally:
        await manager.close()
    connect = Sandbox.resume if info.status.state.lower() == 'paused' else Sandbox.connect
    client = await connect(record.sandbox_ref, connection_config=config)
    await client.renew(timedelta(minutes=settings.AI_BUDDY_AGENT_SANDBOX_TIMEOUT_MINUTES))
    return OpenSandboxWorkspace(
        client, conversation_id=conversation_id, user_id=user_id, permission_mode=permission_mode
    )


async def _create_opensandbox(
    *, conversation_id: str, user_id: int, permission_mode: AIBuddyPermissionMode
) -> tuple[OpenSandboxWorkspace, str]:
    """
    新建 OpenSandbox 实例，非完全权限模式默认拒绝出网

    :param conversation_id: 对话 ID
    :param user_id: 用户 ID
    :param permission_mode: 权限模式
    :return:
    """
    client = await Sandbox.create(
        settings.AI_BUDDY_AGENT_SANDBOX_IMAGE,
        timeout=timedelta(minutes=settings.AI_BUDDY_AGENT_SANDBOX_TIMEOUT_MINUTES),
        resource={'cpu': settings.AI_BUDDY_AGENT_SANDBOX_CPU, 'memory': settings.AI_BUDDY_AGENT_SANDBOX_MEMORY},
        network_policy=None
        if permission_mode == AIBuddyPermissionMode.full
        else NetworkPolicy(default_action='deny', egress=[]),
        connection_config=_connection_config(),
    )
    try:
        await client.files.create_directories([WriteEntry(path=WORKSPACE_ROOT, mode=755)])
    except BaseException:
        await client.close()
        raise
    sandbox = OpenSandboxWorkspace(
        client, conversation_id=conversation_id, user_id=user_id, permission_mode=permission_mode
    )
    return sandbox, client.id


async def _destroy(record: AIBuddySandboxWorkspace) -> None:
    """
    销毁登记对应的 OpenSandbox 实例，已经不存在视为成功，其他失败只记录警告，避免阻断重建和删除

    :param record: 沙箱登记
    :return:
    """
    try:
        manager = await SandboxManager.create(connection_config=_connection_config())
        try:
            await manager.kill_sandbox(record.sandbox_ref)
        finally:
            await manager.close()
    except SandboxApiException as exc:
        if exc.status_code != 404:
            log.warning(f'销毁沙箱失败 ref={record.sandbox_ref}: {exc!r}')
    except (SandboxException, errors.BaseExceptionError) as exc:
        log.warning(f'销毁沙箱失败 ref={record.sandbox_ref}: {exc!r}')


async def open_sandbox(
    *, conversation_id: str, user_id: int, permission_mode: AIBuddyPermissionMode
) -> OpenSandboxWorkspace:
    """
    为对话打开 OpenSandbox 沙箱：优先接回登记的沙箱，网络权限变化时销毁旧沙箱并重建，
    沙箱已被删除时重建并保存新的引用

    :param conversation_id: 对话 ID
    :param user_id: 用户 ID
    :param permission_mode: 权限模式
    :return:
    """
    validate_workspace_id(conversation_id)
    if user_id <= 0:
        raise errors.RequestError(msg='沙箱用户无效')
    reason = sandbox_unavailable_reason()
    if reason is not None:
        raise errors.RequestError(msg=f'服务端沙箱当前不可用：{reason}')
    async with async_db_session.begin() as db:
        stored = await ai_buddy_sandbox_workspace_dao.get(db, user_id, conversation_id)
        record = (
            None
            if stored is None
            else AIBuddySandboxWorkspace(
                user_id=user_id,
                conversation_id=conversation_id,
                sandbox_ref=stored.sandbox_ref,
                permission_mode=stored.permission_mode,
            )
        )
    sandbox: OpenSandboxWorkspace | None = None
    if record is not None:
        # 网络权限收紧时不在同一实例上复用，销毁旧沙箱后重建
        same_network = (record.permission_mode == AIBuddyPermissionMode.full.value) == (
            permission_mode == AIBuddyPermissionMode.full
        )
        if same_network:
            sandbox = await _attach_opensandbox(
                record, conversation_id=conversation_id, user_id=user_id, permission_mode=permission_mode
            )
        if sandbox is None:
            await _destroy(record)
    if sandbox is None:
        sandbox, ref = await _create_opensandbox(
            conversation_id=conversation_id, user_id=user_id, permission_mode=permission_mode
        )
        async with async_db_session.begin() as db:
            await ai_buddy_sandbox_workspace_dao.save(
                db,
                await ai_buddy_sandbox_workspace_dao.get(db, user_id, conversation_id),
                user_id=user_id,
                conversation_id=conversation_id,
                sandbox_ref=ref,
                permission_mode=permission_mode.value,
            )
    return sandbox


async def destroy_conversation_sandbox(*, user_id: int, conversation_id: str) -> None:
    """
    销毁对话沙箱并删除登记，删除对话时调用，即使沙箱不在本进程也能按登记销毁

    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :return:
    """
    live = LIVE_SANDBOXES.pop(conversation_id, None)
    if live is not None:
        await live.stop()
    async with async_db_session.begin() as db:
        record = await ai_buddy_sandbox_workspace_dao.get(db, user_id, conversation_id)
        if record is not None:
            await _destroy(record)
            await ai_buddy_sandbox_workspace_dao.delete(db, record)


async def create_coding_sandbox(
    *,
    conversation_id: str,
    user_id: int,
    permission_mode: AIBuddyPermissionMode,
    execution_backend: AIBuddyExecutionBackend = AIBuddyExecutionBackend.local,
    execution_bridge_id: str | None = None,
) -> CodingSandbox:
    """
    按本轮执行后端创建工作区，本机 OS 沙箱只能通过桌面连接执行，服务端沙箱固定使用 OpenSandbox 接回或新建

    :param conversation_id: 对话 ID
    :param user_id: 用户 ID
    :param permission_mode: 权限模式
    :param execution_backend: 执行后端
    :param execution_bridge_id: 桌面执行连接 ID
    :return:
    """
    if execution_backend == AIBuddyExecutionBackend.local and not execution_bridge_id:
        raise errors.RequestError(msg='本机编码需要从桌面端连接 OS 沙箱工作区，不会在服务器执行')
    if execution_backend == AIBuddyExecutionBackend.sandbox and execution_bridge_id is not None:
        raise errors.RequestError(msg='服务端沙箱不使用桌面执行连接')
    live = get_live_sandbox(conversation_id)
    if live is not None and live.user_id != user_id:
        raise errors.RequestError(msg='编码工作区不属于当前用户')
    if execution_backend == AIBuddyExecutionBackend.sandbox:
        if live is not None:
            await live.stop()
        workspace = await open_sandbox(
            conversation_id=conversation_id,
            user_id=user_id,
            permission_mode=permission_mode,
        )
        LIVE_SANDBOXES[conversation_id] = workspace
        return workspace
    if (
        live is not None
        and live.execution_backend == execution_backend
        and live.permission_mode == permission_mode
        and isinstance(live, DesktopBridgeWorkspace)
        and live.bridge.bridge_id == execution_bridge_id
    ):
        await live.bridge.check_connection()
        return live
    await get_bridge(
        bridge_id=execution_bridge_id, user_id=user_id, backend=execution_backend, permission_mode=permission_mode
    )
    if live is not None:
        await live.stop()
    bridge = await open_bridge(
        bridge_id=execution_bridge_id,
        user_id=user_id,
        backend=execution_backend,
        permission_mode=permission_mode,
        conversation_id=conversation_id,
    )
    workspace = DesktopBridgeWorkspace(bridge, conversation_id=conversation_id)
    LIVE_SANDBOXES[conversation_id] = workspace
    return workspace
