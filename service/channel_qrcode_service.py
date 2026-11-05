import asyncio
import time

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.database.db import uuid4_str
from backend.plugin.ai_buddy.channels.qrcode import (
    CHANNEL_BIND_OPTIONS,
    acquire_qrcode_create_lock,
    cancel_feishu_qrcode,
    channel_display_name,
    delete_qrcode_session,
    load_qrcode_session,
    patch_qrcode_session,
    poll_dingtalk_qrcode,
    poll_qq_qrcode,
    poll_wechat_qrcode,
    poll_wecom_qrcode,
    release_qrcode_create_lock,
    request_dingtalk_qrcode,
    request_qq_qrcode,
    request_wechat_qrcode,
    request_wecom_qrcode,
    save_qrcode_session,
    start_feishu_qrcode,
    supports_channel_qrcode,
)
from backend.plugin.ai_buddy.crud.crud_channel import ai_buddy_channel_dao
from backend.plugin.ai_buddy.enums import AIBuddyChannelQrcodeStatus, AIBuddyChannelType
from backend.plugin.ai_buddy.model.channel import AIBuddyChannel
from backend.plugin.ai_buddy.schema.channel import (
    CreateAIBuddyChannelParam,
    GetAIBuddyChannelBindOptionDetail,
    GetAIBuddyChannelDetail,
    GetAIBuddyChannelQrcodeDetail,
)
from backend.plugin.ai_buddy.service.channel_service import ai_buddy_channel_service


class AIBuddyChannelQrcodeService:
    """通道扫码绑定服务"""

    @staticmethod
    def get_bind_options() -> list[GetAIBuddyChannelBindOptionDetail]:
        """获取各通道绑定方式"""
        return [GetAIBuddyChannelBindOptionDetail(**item) for item in CHANNEL_BIND_OPTIONS]

    async def generate(self, *, user_id: int, channel_type: AIBuddyChannelType) -> GetAIBuddyChannelQrcodeDetail:
        """
        发起通道扫码

        :param user_id: 用户 ID
        :param channel_type: 通道类型
        :return:
        """
        if not supports_channel_qrcode(channel_type):
            raise errors.RequestError(msg='该通道不支持扫码，请手动填写凭证')

        session_id = uuid4_str()
        payload = {
            'session_id': session_id,
            'user_id': user_id,
            'type': channel_type.value,
            'status': AIBuddyChannelQrcodeStatus.wait.value,
            'qrcode_url': None,
            'expire_at': int(time.time()) + 300,
            'platform_token': None,
            'bind_key': None,
            'config': None,
            'channel_id': None,
            'error': None,
        }
        await save_qrcode_session(session_id, payload)

        try:
            if channel_type == AIBuddyChannelType.wechat:
                token, image = await request_wechat_qrcode()
                payload = await patch_qrcode_session(
                    session_id,
                    qrcode_url=image,
                    platform_token=token,
                    expire_at=int(time.time()) + 300,
                )
                return self._to_detail(payload=payload)
            if channel_type == AIBuddyChannelType.wecom:
                scode, url = await request_wecom_qrcode()
                payload = await patch_qrcode_session(
                    session_id,
                    qrcode_url=url,
                    platform_token=scode,
                    expire_at=int(time.time()) + 300,
                )
                return self._to_detail(payload=payload)
            if channel_type == AIBuddyChannelType.dingtalk:
                device_code, url, expire_in = await request_dingtalk_qrcode()
                payload = await patch_qrcode_session(
                    session_id,
                    qrcode_url=url,
                    platform_token=device_code,
                    expire_at=int(time.time()) + expire_in,
                )
                return self._to_detail(payload=payload)
            if channel_type == AIBuddyChannelType.qq:
                task_id, bind_key, url = await request_qq_qrcode()
                payload = await patch_qrcode_session(
                    session_id,
                    qrcode_url=url,
                    platform_token=task_id,
                    bind_key=bind_key,
                    expire_at=int(time.time()) + 300,
                )
                return self._to_detail(payload=payload)
            url, expire_in = await start_feishu_qrcode(session_id=session_id)
            payload = await patch_qrcode_session(
                session_id,
                qrcode_url=url,
                expire_at=int(time.time()) + expire_in,
            )
            return self._to_detail(payload=payload)
        except asyncio.CancelledError:
            await cancel_feishu_qrcode(session_id)
            await delete_qrcode_session(session_id)
            raise
        except Exception as exc:
            await cancel_feishu_qrcode(session_id)
            await delete_qrcode_session(session_id)
            if isinstance(exc, errors.RequestError):
                raise
            raise errors.RequestError(msg=f'{channel_display_name(channel_type)}二维码生成失败，请重试') from exc

    async def poll(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        channel_type: AIBuddyChannelType,
        session_id: str,
    ) -> GetAIBuddyChannelQrcodeDetail:
        """
        轮询扫码状态，确认后创建通道

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param channel_type: 通道类型
        :param session_id: 扫码会话 ID
        :return:
        """
        payload = await load_qrcode_session(session_id)
        if payload is None or payload.get('user_id') != user_id:
            raise errors.NotFoundError(msg='扫码会话不存在或已过期')
        if payload.get('type') != channel_type.value:
            raise errors.RequestError(msg='扫码会话与通道类型不匹配')

        if payload.get('status') in {
            AIBuddyChannelQrcodeStatus.wait.value,
            AIBuddyChannelQrcodeStatus.scanned.value,
        }:
            if int(payload.get('expire_at') or 0) <= int(time.time()):
                payload = await patch_qrcode_session(
                    session_id, status=AIBuddyChannelQrcodeStatus.expired.value, error='二维码已过期，请重新扫码'
                )
            else:
                poller = {
                    AIBuddyChannelType.wechat: poll_wechat_qrcode,
                    AIBuddyChannelType.wecom: poll_wecom_qrcode,
                    AIBuddyChannelType.dingtalk: poll_dingtalk_qrcode,
                    AIBuddyChannelType.qq: poll_qq_qrcode,
                }.get(channel_type)
                if poller:
                    try:
                        payload = await poller(session_id=session_id, payload=payload)
                    except errors.NotFoundError:
                        raise
                    except Exception:
                        payload = await patch_qrcode_session(
                            session_id,
                            status=AIBuddyChannelQrcodeStatus.error.value,
                            error=f'{channel_display_name(channel_type)}扫码查询失败，请重新扫码',
                        )
        if payload.get('status') in {
            AIBuddyChannelQrcodeStatus.expired.value,
            AIBuddyChannelQrcodeStatus.error.value,
        }:
            await cancel_feishu_qrcode(session_id)

        if payload.get('status') == AIBuddyChannelQrcodeStatus.confirmed.value and payload.get('config'):
            return await self._bind_confirmed_channel(
                db=db,
                user_id=user_id,
                channel_type=channel_type,
                session_id=session_id,
                payload=payload,
            )
        return self._to_detail(payload=payload)

    async def _bind_confirmed_channel(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        channel_type: AIBuddyChannelType,
        session_id: str,
        payload: dict[str, Any],
    ) -> GetAIBuddyChannelQrcodeDetail:
        """
        在会话锁内串行完成通道创建与绑定

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param channel_type: 通道类型
        :param session_id: 扫码会话 ID
        :param payload: 当前扫码会话数据
        :return:
        """
        lock_token = uuid4_str()
        for _ in range(50):
            acquired = await acquire_qrcode_create_lock(session_id=session_id, token=lock_token)
            if acquired:
                break
            await asyncio.sleep(0.1)
        else:
            raise errors.RequestError(msg='通道正在创建，请稍后重试')
        try:
            current = await load_qrcode_session(session_id)
            if current is None or current.get('user_id') != user_id:
                raise errors.NotFoundError(msg='扫码会话不存在或已过期')
            if current.get('type') != channel_type.value:
                raise errors.RequestError(msg='扫码会话与通道类型不匹配')
            if current.get('status') != AIBuddyChannelQrcodeStatus.confirmed.value or not current.get('config'):
                return self._to_detail(payload=current)
            channel = await self._get_existing_channel(db=db, user_id=user_id, payload=current)
            if channel is None:
                channel = await self._create_confirmed_channel(
                    db=db, user_id=user_id, channel_type=channel_type, payload=current
                )
                await patch_qrcode_session(session_id, channel_id=channel.id)
            current = await load_qrcode_session(session_id) or current
            return self._to_detail(payload=current, channel=GetAIBuddyChannelDetail.model_validate(channel))
        finally:
            await release_qrcode_create_lock(session_id=session_id, token=lock_token)

    @staticmethod
    async def _get_existing_channel(
        *, db: AsyncSession, user_id: int, payload: dict[str, Any]
    ) -> AIBuddyChannel | None:
        """
        读取会话已绑定的通道，兼容另一请求尚未提交事务的短暂窗口

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param payload: 扫码会话数据
        :return:
        """
        channel_id = payload.get('channel_id')
        if not channel_id:
            return None
        for _ in range(20):
            try:
                return await ai_buddy_channel_service.get(db=db, pk=int(channel_id), user_id=user_id)
            except errors.NotFoundError:
                await asyncio.sleep(0.05)
        return None

    @staticmethod
    async def _create_confirmed_channel(
        *,
        db: AsyncSession,
        user_id: int,
        channel_type: AIBuddyChannelType,
        payload: dict[str, Any],
    ) -> AIBuddyChannel:
        """
        为已确认扫码创建唯一通道

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param channel_type: 通道类型
        :param payload: 扫码会话数据
        :return:
        """
        base = channel_display_name(channel_type)
        name = base
        index = 2
        for _ in range(100):
            if await ai_buddy_channel_dao.get_by_name(db, user_id, name):
                name = f'{base}-{index}'
                index += 1
                continue
            try:
                async with db.begin_nested():
                    await ai_buddy_channel_service.create(
                        db=db,
                        user_id=user_id,
                        obj=CreateAIBuddyChannelParam(
                            name=name,
                            type=channel_type,
                            config=payload.get('config'),
                            status=StatusType.enable,
                        ),
                    )
                    await db.flush()
            except IntegrityError:
                continue
            channel = await ai_buddy_channel_dao.get_by_name(db, user_id, name)
            if channel is not None:
                return channel
            name = f'{base}-{index}'
            index += 1
        raise errors.ServerError(msg='扫码创建通道失败')

    @staticmethod
    async def cancel(*, user_id: int, channel_type: AIBuddyChannelType, session_id: str) -> None:
        """
        取消扫码会话并停止飞书后台轮询

        :param user_id: 用户 ID
        :param channel_type: 通道类型
        :param session_id: 扫码会话 ID
        :return:
        """
        payload = await load_qrcode_session(session_id)
        if payload is None or payload.get('user_id') != user_id:
            return
        if payload.get('type') != channel_type.value:
            raise errors.RequestError(msg='扫码会话与通道类型不匹配')

        await cancel_feishu_qrcode(session_id)
        await delete_qrcode_session(session_id)

    @staticmethod
    def _to_detail(
        *, payload: dict[str, Any], channel: GetAIBuddyChannelDetail | None = None
    ) -> GetAIBuddyChannelQrcodeDetail:
        """
        将扫码会话转换为客户端状态详情

        :param payload: 扫码会话内容
        :param channel: 已绑定通道详情
        :return:
        """
        return GetAIBuddyChannelQrcodeDetail(
            session_id=str(payload['session_id']),
            type=AIBuddyChannelType(payload['type']),
            status=AIBuddyChannelQrcodeStatus(payload['status']),
            qrcode_url=payload.get('qrcode_url'),
            expire_in=None
            if payload.get('expire_at') is None
            else max(int(payload['expire_at']) - int(time.time()), 0),
            channel=channel,
            error=payload.get('error'),
        )


ai_buddy_channel_qrcode_service: AIBuddyChannelQrcodeService = AIBuddyChannelQrcodeService()
