from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Header, Path, Query, Request
from starlette.responses import StreamingResponse

from backend.common.pagination import CursorPageData, DependsCursorPagination
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.conversation import (
    AIBuddyConversationDetailQueryParam,
    AIBuddyConversationEventsHeaderParam,
    AIBuddyConversationQueryParam,
    GetAIBuddyConversationDetail,
    GetAIBuddyConversationListDetail,
    ResolveAIBuddyCodingApprovalParam,
    UpdateAIBuddyConversationArchiveParam,
    UpdateAIBuddyConversationPinnedParam,
    UpdateAIBuddyConversationSourceParam,
    UpdateAIBuddyConversationTitleParam,
    UpdateAIBuddyConversationWorkspaceParam,
)
from backend.plugin.ai_buddy.schema.delegation import ControlAIBuddyDelegationParam
from backend.plugin.ai_buddy.schema.follow_up import (
    GetAIBuddyFollowUpDetail,
    GetAIBuddyFollowUpsDetail,
    SubmitAIBuddyFollowUpParam,
    UpdateAIBuddyFollowUpParam,
)
from backend.plugin.ai_buddy.schema.input_request import (
    GetAIBuddyInputRequestsDetail,
    ResolveAIBuddyInputRequestParam,
)
from backend.plugin.ai_buddy.schema.message_history import ForkAIBuddyConversationParam, GetAIBuddyPlanDetail
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.service.delegation_service import ai_buddy_delegation_service
from backend.plugin.ai_buddy.service.follow_up_service import ai_buddy_follow_up_service
from backend.plugin.ai_buddy.service.input_request_service import ai_buddy_input_request_service
from backend.plugin.ai_buddy.service.message_history_service import ai_buddy_message_history_service

router = APIRouter()


@router.get('/{pk}/delegations', summary='获取本轮子代理状态', dependencies=[DependsJwtAuth])
async def get_ai_buddy_delegations(
    request: Request,
    db: CurrentSession,
    pk: str,
    run_id: Annotated[str, Query(min_length=1, max_length=128)],
) -> ResponseModel:
    data = await ai_buddy_delegation_service.get_list(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        run_id=run_id,
    )
    return response_base.success(data=data)


@router.post('/{pk}/delegations/{task_id}', summary='引导或停止本轮子代理', dependencies=[DependsJwtAuth])
async def control_ai_buddy_delegation(
    request: Request,
    db: CurrentSession,
    pk: str,
    task_id: UUID,
    obj: ControlAIBuddyDelegationParam,
) -> ResponseModel:
    await ai_buddy_delegation_service.control(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        task_id=task_id.hex,
        obj=obj,
    )
    return response_base.success()


@router.get('/{pk}/input-requests', summary='恢复未决问题与密钥请求', dependencies=[DependsJwtAuth])
async def get_ai_buddy_input_requests(
    request: Request,
    db: CurrentSession,
    pk: str,
) -> ResponseSchemaModel[GetAIBuddyInputRequestsDetail]:
    data = await ai_buddy_input_request_service.get_list(db=db, conversation_id=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post('/{pk}/input-requests/{request_id}', summary='回复当前运行的输入请求', dependencies=[DependsJwtAuth])
async def resolve_ai_buddy_input_request(
    request: Request,
    db: CurrentSession,
    pk: str,
    request_id: UUID,
    obj: ResolveAIBuddyInputRequestParam,
) -> ResponseModel:
    await ai_buddy_input_request_service.resolve(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        request_id=request_id.hex,
        obj=obj,
    )
    return response_base.success()


@router.get(
    '',
    summary='分页获取所有对话列表',
    dependencies=[
        DependsJwtAuth,
        DependsCursorPagination,
    ],
)
async def get_ai_buddy_conversations_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyConversationQueryParam, Query()],
) -> ResponseSchemaModel[CursorPageData[GetAIBuddyConversationListDetail]]:
    data = await ai_buddy_conversation_service.get_list(
        db=db,
        user_id=request.user.id,
        project_id=query.project_id,
        assistant_id=query.assistant_id,
        q=query.q,
        archived=query.archived,
        surface=query.surface,
        view=query.view,
        agent_mode=query.agent_mode,
    )
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取对话详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_conversation(
    request: Request,
    db: CurrentSession,
    pk: Annotated[str, Path(description='对话 ID')],
    query: Annotated[AIBuddyConversationDetailQueryParam, Query()],
) -> ResponseSchemaModel[GetAIBuddyConversationDetail]:
    data = await ai_buddy_conversation_service.get(
        db=db, conversation_id=pk, user_id=request.user.id, message_limit=query.message_limit
    )
    return response_base.success(data=data)


@router.put('/{pk}', summary='更新对话标题', dependencies=[DependsJwtAuth])
async def update_ai_buddy_conversation(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[str, Path(description='对话 ID')],
    obj: UpdateAIBuddyConversationTitleParam,
) -> ResponseModel:
    count = await ai_buddy_conversation_service.update(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        obj=obj,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.put('/{pk}/pin', summary='更新对话置顶状态', dependencies=[DependsJwtAuth])
async def update_ai_buddy_conversation_pinned_status(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[str, Path(description='对话 ID')],
    obj: UpdateAIBuddyConversationPinnedParam,
) -> ResponseModel:
    count = await ai_buddy_conversation_service.update_pinned_status(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        obj=obj,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.put('/{pk}/archive', summary='更新对话归档状态', dependencies=[DependsJwtAuth])
async def update_ai_buddy_conversation_archive_status(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[str, Path(description='对话 ID')],
    obj: UpdateAIBuddyConversationArchiveParam,
) -> ResponseModel:
    count = await ai_buddy_conversation_service.update_archive_status(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        obj=obj,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.put(
    '/{pk}/source',
    summary='迁移对话事实源',
    description=(
        '在云端与本机之间切换以谁为准；会话 ID、消息顺序、附件引用和删除状态不变，'
        '迁移前会停止当前生成，已是目标事实源时返回失败'
    ),
    dependencies=[DependsJwtAuth],
)
async def update_ai_buddy_conversation_source(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[str, Path(description='对话 ID')],
    obj: UpdateAIBuddyConversationSourceParam,
) -> ResponseModel:
    count = await ai_buddy_conversation_service.update_source(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        obj=obj,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.put('/{pk}/workspace', summary='更新对话工作区', dependencies=[DependsJwtAuth])
async def update_ai_buddy_conversation_workspace(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[str, Path(description='对话 ID')],
    obj: UpdateAIBuddyConversationWorkspaceParam,
) -> ResponseModel:
    count = await ai_buddy_conversation_service.update_workspace(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        obj=obj,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post('/{pk}/fork', summary='复刻对话', dependencies=[DependsJwtAuth])
async def fork_ai_buddy_conversation(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[str, Path(description='对话 ID')],
    obj: Annotated[ForkAIBuddyConversationParam | None, Body()] = None,
) -> ResponseSchemaModel[str]:
    conversation_id = await ai_buddy_conversation_service.fork(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        message_id=obj.message_id if obj else None,
        include_message=obj.include_message if obj else True,
    )
    return response_base.success(data=conversation_id)


@router.get('/{pk}/plan', summary='读取当前任务计划', dependencies=[DependsJwtAuth])
async def get_ai_buddy_conversation_plan(
    request: Request,
    db: CurrentSession,
    pk: str,
) -> ResponseSchemaModel[GetAIBuddyPlanDetail]:
    data = await ai_buddy_message_history_service.plan(db=db, conversation_id=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '/{pk}/events',
    summary='订阅对话当前生成流',
    description=(
        '切回对话时先拉详情再接此流；重放本轮已产生的事件并继续订阅，直到结束、失败或停止；'
        '每个事件带 SSE id，断线重连时通过 Last-Event-ID 请求头从该事件之后续传'
    ),
    dependencies=[DependsJwtAuth],
)
async def subscribe_ai_buddy_conversation_events(
    request: Request,
    db: CurrentSession,
    pk: Annotated[str, Path(description='对话 ID')],
    headers: Annotated[AIBuddyConversationEventsHeaderParam, Header()],
) -> StreamingResponse:
    return await ai_buddy_conversation_service.subscribe_events(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        after_id=headers.last_event_id,
    )


@router.post(
    '/{pk}/stop',
    summary='停止对话生成',
    dependencies=[DependsJwtAuth],
)
async def stop_ai_buddy_conversation_generation(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[str, Path(description='对话 ID')],
) -> ResponseModel:
    await ai_buddy_conversation_service.stop_generation(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
    )
    return response_base.success()


@router.post('/{pk}/approvals/{request_id}', summary='提交编码工具审批', dependencies=[DependsJwtAuth])
async def resolve_ai_buddy_coding_approval(
    request: Request,
    db: CurrentSession,
    pk: str,
    request_id: UUID,
    obj: ResolveAIBuddyCodingApprovalParam,
) -> ResponseModel:
    await ai_buddy_conversation_service.resolve_coding_approval(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        request_id=request_id.hex,
        approved=obj.approved,
    )
    return response_base.success()


@router.delete('/{pk}', summary='删除对话', dependencies=[DependsJwtAuth])
async def delete_ai_buddy_conversation(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[str, Path(description='对话 ID')],
) -> ResponseModel:
    count = await ai_buddy_conversation_service.delete(db=db, conversation_id=pk, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post('/{pk}/follow-ups', summary='提交持久跟进或引导', dependencies=[DependsJwtAuth])
async def submit_ai_buddy_follow_up(
    request: Request,
    db: CurrentSessionTransaction,
    pk: str,
    obj: SubmitAIBuddyFollowUpParam,
) -> ResponseSchemaModel[GetAIBuddyFollowUpDetail]:
    data = await ai_buddy_follow_up_service.submit(db=db, conversation_id=pk, user_id=request.user.id, obj=obj)
    return response_base.success(data=data)


@router.get('/{pk}/follow-ups', summary='获取持久跟进列表', dependencies=[DependsJwtAuth])
async def get_ai_buddy_follow_ups(
    request: Request,
    db: CurrentSession,
    pk: str,
) -> ResponseSchemaModel[GetAIBuddyFollowUpsDetail]:
    data = await ai_buddy_follow_up_service.get_list(db=db, conversation_id=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.patch('/{pk}/follow-ups/{followup_id}', summary='修改或移动待执行跟进', dependencies=[DependsJwtAuth])
async def update_ai_buddy_follow_up(
    request: Request,
    db: CurrentSessionTransaction,
    pk: str,
    followup_id: int,
    obj: UpdateAIBuddyFollowUpParam,
) -> ResponseSchemaModel[GetAIBuddyFollowUpDetail]:
    data = await ai_buddy_follow_up_service.update(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        followup_id=followup_id,
        obj=obj,
    )
    return response_base.success(data=data)


@router.delete('/{pk}/follow-ups/{followup_id}', summary='删除待执行跟进', dependencies=[DependsJwtAuth])
async def delete_ai_buddy_follow_up(
    request: Request,
    db: CurrentSessionTransaction,
    pk: str,
    followup_id: int,
) -> ResponseModel:
    await ai_buddy_follow_up_service.delete(
        db=db,
        conversation_id=pk,
        user_id=request.user.id,
        followup_id=followup_id,
    )
    return response_base.success()
