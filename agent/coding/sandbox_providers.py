import importlib

from dataclasses import dataclass
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.exceptions import SandboxApiException, SandboxException
from opensandbox.manager import SandboxManager
from opensandbox.models.filesystem import WriteEntry
from opensandbox.models.sandboxes import NetworkPolicy
from pydantic_ai.workspaces import Workspace, WorkspaceError, WorkspaceRef

from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.coding.sandbox import _LIVE, _WORKSPACE, CodingSandbox, OpenSandboxWorkspace
from backend.plugin.ai_buddy.agent.coding.workspace_sandbox import WorkspaceSandbox
from backend.plugin.ai_buddy.crud.crud_sandbox_workspace import ai_buddy_sandbox_workspace_dao
from backend.plugin.ai_buddy.enums import AIBuddyPermissionMode, AIBuddySandboxProvider
from backend.plugin.ai_buddy.model.sandbox_workspace import AIBuddySandboxWorkspace
from backend.plugin.ai_buddy.utils.workspace import validate_workspace_id


@dataclass(frozen=True, slots=True)
class HarnessProvider:
    """Pydantic AI harness 沙箱服务商，capability 负责按引用接回和销毁，backend 负责新建"""

    module: str
    capability: str
    backend: str
    extra: str
    image_kwarg: str | None
    network_kwarg: bool


_SUPPORTED_PROVIDERS = frozenset(AIBuddySandboxProvider)

_HARNESS_PROVIDERS: dict[str, HarnessProvider] = {
    AIBuddySandboxProvider.docker: HarnessProvider(
        'docker_sandbox', 'DockerSandbox', 'DockerSandboxBackend', 'docker', 'image', True
    ),
    AIBuddySandboxProvider.e2b: HarnessProvider(
        'e2b_sandbox', 'E2BSandbox', 'E2BSandboxBackend', 'e2b', 'template', True
    ),
    AIBuddySandboxProvider.modal: HarnessProvider(
        'modal_sandbox', 'ModalSandbox', 'ModalSandboxBackend', 'modal', 'image', False
    ),
    AIBuddySandboxProvider.daytona: HarnessProvider(
        'daytona_sandbox', 'DaytonaSandbox', 'DaytonaSandboxBackend', 'daytona', 'snapshot', True
    ),
    AIBuddySandboxProvider.sprites: HarnessProvider(
        'sprites_sandbox', 'SpritesSandbox', 'SpritesSandboxBackend', 'sprites', None, False
    ),
    AIBuddySandboxProvider.smol: HarnessProvider(
        'smol_sandbox', 'SmolSandbox', 'SmolSandboxBackend', 'smol', 'image', True
    ),
    AIBuddySandboxProvider.boxlite: HarnessProvider(
        'boxlite_sandbox', 'BoxLiteSandbox', 'BoxLiteSandboxBackend', 'boxlite', 'image', True
    ),
}


def resolve_provider(requested: str | None) -> str:
    """
    解析本轮沙箱服务商，未指定时使用配置的默认服务商

    :param requested: 客户端请求的服务商，为空使用配置的默认服务商
    :return:
    """
    provider = requested or settings.AI_BUDDY_AGENT_SANDBOX_PROVIDER
    if provider not in _SUPPORTED_PROVIDERS:
        raise errors.RequestError(msg=f'不支持的沙箱服务商 {provider}')
    return provider


def _load_harness(provider: str) -> tuple[HarnessProvider, type, type]:
    """
    按需加载 harness 沙箱模块，缺少依赖时给出安装提示

    :param provider: 沙箱服务商
    :return:
    """
    spec = _HARNESS_PROVIDERS[provider]
    try:
        module = importlib.import_module(f'pydantic_ai_harness.{spec.module}')
    except ImportError as exc:
        raise errors.RequestError(
            msg=f'沙箱服务商 {provider} 未安装依赖，请执行 uv add "pydantic-ai-harness[{spec.extra}]"'
        ) from exc
    return spec, getattr(module, spec.capability), getattr(module, spec.backend)


def _connection_config() -> ConnectionConfig:
    """构建 OpenSandbox 连接配置"""
    domain = settings.AI_BUDDY_OPENSANDBOX_DOMAIN.strip()
    if not domain:
        raise errors.RequestError(msg='未配置 OpenSandbox 地址')
    return ConnectionConfig(
        domain=domain,
        api_key=settings.AI_BUDDY_OPENSANDBOX_API_KEY.strip() or None,
        protocol=settings.AI_BUDDY_OPENSANDBOX_PROTOCOL,
        use_server_proxy=True,
    )


async def _attach_opensandbox(
    record: AIBuddySandboxWorkspace, *, conversation_id: str, user_id: int, permission_mode: AIBuddyPermissionMode
) -> CodingSandbox | None:
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
) -> tuple[CodingSandbox, str]:
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
        await client.files.create_directories([WriteEntry(path=_WORKSPACE, mode=755)])
    except BaseException:
        await client.close()
        raise
    sandbox = OpenSandboxWorkspace(
        client, conversation_id=conversation_id, user_id=user_id, permission_mode=permission_mode
    )
    return sandbox, client.id


async def _attach_harness(
    provider: str,
    record: AIBuddySandboxWorkspace,
    *,
    conversation_id: str,
    user_id: int,
    permission_mode: AIBuddyPermissionMode,
) -> CodingSandbox | None:
    """
    按引用接回 harness 沙箱，已停止或暂停的实例会被服务商自动唤醒，已删除返回空

    :param provider: 沙箱服务商
    :param record: 沙箱登记
    :param conversation_id: 对话 ID
    :param user_id: 用户 ID
    :param permission_mode: 权限模式
    :return:
    """
    _, capability, _ = _load_harness(provider)
    ref_provider, _, ref_id = record.sandbox_ref.partition(':')
    workspace = Workspace(capability().backend(WorkspaceRef(provider=ref_provider, id=ref_id)))
    try:
        await workspace.run(['true'], timeout=120)
    except WorkspaceError as exc:
        log.warning(f'沙箱已不可用 provider={provider} conversation_id={conversation_id}: {exc}')
        return None
    return WorkspaceSandbox(
        workspace, provider=provider, conversation_id=conversation_id, user_id=user_id, permission_mode=permission_mode
    )


async def _create_harness(
    provider: str, *, conversation_id: str, user_id: int, permission_mode: AIBuddyPermissionMode
) -> tuple[CodingSandbox, str]:
    """
    新建 harness 沙箱，首次执行命令时服务商才真正创建实例，完全权限之外一律禁止出网

    :param provider: 沙箱服务商
    :param conversation_id: 对话 ID
    :param user_id: 用户 ID
    :param permission_mode: 权限模式
    :return:
    """
    spec, _, backend_cls = _load_harness(provider)
    kwargs: dict[str, object] = {'working_dir': _WORKSPACE}
    if spec.image_kwarg:
        kwargs[spec.image_kwarg] = settings.AI_BUDDY_AGENT_SANDBOX_IMAGE
    if spec.network_kwarg:
        kwargs['allow_internet_access'] = permission_mode == AIBuddyPermissionMode.full
    backend = backend_cls(**kwargs)
    workspace = Workspace(backend)
    try:
        await workspace.run(['mkdir', '-p', _WORKSPACE], timeout=300)
    except WorkspaceError as exc:
        raise errors.RequestError(msg=f'沙箱服务商 {provider} 创建沙箱失败：{exc}') from exc
    ref = backend.ref
    if ref is None:
        raise errors.RequestError(msg=f'沙箱服务商 {provider} 未返回沙箱引用')
    sandbox = WorkspaceSandbox(
        workspace, provider=provider, conversation_id=conversation_id, user_id=user_id, permission_mode=permission_mode
    )
    return sandbox, f'{ref.provider}:{ref.id}'


async def _destroy(record: AIBuddySandboxWorkspace) -> None:
    """
    销毁登记对应的沙箱，已经不存在视为成功，其他失败只记录警告，避免阻断切换和删除

    :param record: 沙箱登记
    :return:
    """
    try:
        if record.provider == AIBuddySandboxProvider.opensandbox:
            manager = await SandboxManager.create(connection_config=_connection_config())
            try:
                await manager.kill_sandbox(record.sandbox_ref)
            finally:
                await manager.close()
        else:
            _, capability, _ = _load_harness(record.provider)
            ref_provider, _, ref_id = record.sandbox_ref.partition(':')
            await capability().destroy(WorkspaceRef(provider=ref_provider, id=ref_id))
    except SandboxApiException as exc:
        if exc.status_code != 404:
            log.warning(f'销毁沙箱失败 provider={record.provider} ref={record.sandbox_ref}: {exc!r}')
    except (SandboxException, WorkspaceError, errors.BaseExceptionError) as exc:
        log.warning(f'销毁沙箱失败 provider={record.provider} ref={record.sandbox_ref}: {exc!r}')


async def open_sandbox(
    *,
    conversation_id: str,
    user_id: int,
    permission_mode: AIBuddyPermissionMode,
    requested_provider: str | None = None,
) -> CodingSandbox:
    """
    为对话打开沙箱：优先接回登记的沙箱，服务商或网络权限变化时销毁旧沙箱并在新的服务商上重建，
    沙箱已被删除时重建并保存新的引用

    :param conversation_id: 对话 ID
    :param user_id: 用户 ID
    :param permission_mode: 权限模式
    :param requested_provider: 本轮请求的服务商
    :return:
    """
    validate_workspace_id(conversation_id)
    if user_id <= 0:
        raise errors.RequestError(msg='沙箱用户无效')
    provider = resolve_provider(requested_provider)
    async with async_db_session.begin() as db:
        stored = await ai_buddy_sandbox_workspace_dao.get(db, user_id, conversation_id)
        record = (
            None
            if stored is None
            else AIBuddySandboxWorkspace(
                user_id=user_id,
                conversation_id=conversation_id,
                provider=stored.provider,
                sandbox_ref=stored.sandbox_ref,
                permission_mode=stored.permission_mode,
            )
        )
    sandbox: CodingSandbox | None = None
    if record is not None:
        # 服务商切换或网络权限收紧时不复用，旧沙箱销毁后在目标服务商上重建
        same_network = (record.permission_mode == AIBuddyPermissionMode.full.value) == (
            permission_mode == AIBuddyPermissionMode.full
        )
        if record.provider == provider and same_network:
            kwargs = {'conversation_id': conversation_id, 'user_id': user_id, 'permission_mode': permission_mode}
            if provider == AIBuddySandboxProvider.opensandbox:
                sandbox = await _attach_opensandbox(record, **kwargs)
            else:
                sandbox = await _attach_harness(provider, record, **kwargs)
        if sandbox is None:
            await _destroy(record)
    if sandbox is None:
        if provider == AIBuddySandboxProvider.opensandbox:
            sandbox, ref = await _create_opensandbox(
                conversation_id=conversation_id, user_id=user_id, permission_mode=permission_mode
            )
        else:
            sandbox, ref = await _create_harness(
                provider, conversation_id=conversation_id, user_id=user_id, permission_mode=permission_mode
            )
        async with async_db_session.begin() as db:
            await ai_buddy_sandbox_workspace_dao.save(
                db,
                await ai_buddy_sandbox_workspace_dao.get(db, user_id, conversation_id),
                user_id=user_id,
                conversation_id=conversation_id,
                provider=provider,
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
    live = _LIVE.pop(conversation_id, None)
    if live is not None:
        await live.stop()
    async with async_db_session.begin() as db:
        record = await ai_buddy_sandbox_workspace_dao.get(db, user_id, conversation_id)
        if record is not None:
            await _destroy(record)
            await ai_buddy_sandbox_workspace_dao.delete(db, record)
