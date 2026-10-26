from typing import Annotated, Any

from fastapi import APIRouter, Body, Path, Query, Request

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.enums import AIBuddyChannelType
from backend.plugin.ai_buddy.schema.channel import (
    AIBuddyChannelHitlQueryParam,
    CreateAIBuddyChannelParam,
    CreateAIBuddyChannelQrcodePollParam,
    GetAIBuddyChannelBindOptionDetail,
    GetAIBuddyChannelDetail,
    GetAIBuddyChannelQrcodeDetail,
    UpdateAIBuddyChannelParam,
)
from backend.plugin.ai_buddy.service.channel_inbound_service import ai_buddy_channel_inbound_service
from backend.plugin.ai_buddy.service.channel_qrcode_service import ai_buddy_channel_qrcode_service
from backend.plugin.ai_buddy.service.channel_service import ai_buddy_channel_service

router = APIRouter()


@router.get('/all', summary='获取所有通道', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_channels(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetAIBuddyChannelDetail]]:
    data = await ai_buddy_channel_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get('/bind-options', summary='获取通道绑定方式', dependencies=[DependsJwtAuth])
async def get_ai_buddy_channel_bind_options() -> ResponseSchemaModel[list[GetAIBuddyChannelBindOptionDetail]]:
    data = ai_buddy_channel_qrcode_service.get_bind_options()
    return response_base.success(data=data)


@router.post(
    '/qrcode/{channel_type}',
    summary='发起通道扫码',
    dependencies=[DependsJwtAuth],
)
async def generate_ai_buddy_channel_qrcode(
    request: Request,
    channel_type: Annotated[AIBuddyChannelType, Path(description='通道类型')],
) -> ResponseSchemaModel[GetAIBuddyChannelQrcodeDetail]:
    data = await ai_buddy_channel_qrcode_service.generate(user_id=request.user.id, channel_type=channel_type)
    return response_base.success(data=data)


@router.post(
    '/qrcode/{channel_type}/cancel',
    summary='取消通道扫码',
    dependencies=[DependsJwtAuth],
)
async def cancel_ai_buddy_channel_qrcode(
    request: Request,
    channel_type: Annotated[AIBuddyChannelType, Path(description='通道类型')],
    obj: CreateAIBuddyChannelQrcodePollParam,
) -> ResponseModel:
    await ai_buddy_channel_qrcode_service.cancel(
        user_id=request.user.id,
        channel_type=channel_type,
        session_id=obj.session_id,
    )
    return response_base.success()


@router.post(
    '/qrcode/{channel_type}/poll',
    summary='轮询通道扫码',
    dependencies=[DependsJwtAuth],
)
async def poll_ai_buddy_channel_qrcode(
    request: Request,
    db: CurrentSessionTransaction,
    channel_type: Annotated[AIBuddyChannelType, Path(description='通道类型')],
    obj: CreateAIBuddyChannelQrcodePollParam,
) -> ResponseSchemaModel[GetAIBuddyChannelQrcodeDetail]:
    data = await ai_buddy_channel_qrcode_service.poll(
        db=db,
        user_id=request.user.id,
        channel_type=channel_type,
        session_id=obj.session_id,
    )
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取通道详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_channel(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='通道 ID')],
) -> ResponseSchemaModel[GetAIBuddyChannelDetail]:
    data = await ai_buddy_channel_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建通道',
    dependencies=[DependsJwtAuth],
)
async def create_ai_buddy_channel(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyChannelParam,
) -> ResponseModel:
    await ai_buddy_channel_service.create(db=db, obj=obj, user_id=request.user.id)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新通道',
    dependencies=[DependsJwtAuth],
)
async def update_ai_buddy_channel(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='通道 ID')],
    obj: UpdateAIBuddyChannelParam,
) -> ResponseModel:
    count = await ai_buddy_channel_service.update(db=db, pk=pk, obj=obj, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除通道',
    dependencies=[DependsJwtAuth],
)
async def delete_ai_buddy_channel(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='通道 ID')],
) -> ResponseModel:
    count = await ai_buddy_channel_service.delete(db=db, pk=pk, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post('/{pk}/inbound', summary='通道入站', dependencies=[DependsJwtAuth])
async def inbound_ai_buddy_channel(
    request: Request,
    pk: Annotated[int, Path(description='通道 ID')],
    payload: Annotated[dict[str, Any], Body(default_factory=dict)],
) -> Any:
    return await ai_buddy_channel_inbound_service.handle_inbound(
        pk=pk,
        user_id=request.user.id,
        payload=payload,
    )


@router.post('/{pk}/hitl', summary='构造 IM 审批卡片', dependencies=[DependsJwtAuth])
async def hitl_ai_buddy_channel(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='通道 ID')],
    query: Annotated[AIBuddyChannelHitlQueryParam, Query()],
) -> ResponseSchemaModel[dict[str, Any]]:
    data = await ai_buddy_channel_inbound_service.build_approval_card(
        db=db,
        pk=pk,
        user_id=request.user.id,
        conversation_id=query.conversation_id,
        tool_name=query.tool_name,
        reason=query.reason,
    )
    return response_base.success(data=data)
