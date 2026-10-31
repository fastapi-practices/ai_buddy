from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.ai_buddy.crud.crud_knowledge import ai_buddy_knowledge_dao
from backend.plugin.ai_buddy.crud.crud_knowledge_base import ai_buddy_knowledge_base_dao
from backend.plugin.ai_buddy.model.knowledge_base import AIBuddyKnowledgeBase
from backend.plugin.ai_buddy.schema.knowledge_base import (
    CreateAIBuddyKnowledgeBaseParam,
    UpdateAIBuddyKnowledgeBaseParam,
)
from backend.plugin.ai_buddy.schema.onnx_option import (
    GetAIBuddyOnnxCatalogDetail,
    GetAIBuddyOnnxDownloadStatusDetail,
    GetAIBuddyOnnxOptionDetail,
)
from backend.plugin.ai_buddy.service.knowledge_service import ai_buddy_knowledge_service
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config
from backend.plugin.ai_buddy.utils.knowledge_ocr import (
    get_ocr_onnx_download_status,
    get_paddleocr_download_status,
    list_onnx_ocr_options,
    list_paddleocr_options,
    ocr_models_dir,
    paddleocr_models_dir,
    start_ocr_onnx_download,
    start_paddleocr_download,
)
from backend.plugin.ai_buddy.utils.onnx_embed import (
    embedding_models_dir,
    get_onnx_download_status,
    list_onnx_embedding_options,
    start_onnx_download,
)
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID


class AIBuddyKnowledgeBaseService:
    """AI 知识库服务类"""

    @staticmethod
    async def get_onnx_options() -> GetAIBuddyOnnxCatalogDetail:
        """获取本地向量和 OCR 模型目录"""
        embedding = await run_in_threadpool(list_onnx_embedding_options)
        ocr = await run_in_threadpool(list_onnx_ocr_options)
        paddleocr = await run_in_threadpool(list_paddleocr_options)
        cache_dir = await run_in_threadpool(embedding_models_dir)
        ocr_cache_dir = await run_in_threadpool(ocr_models_dir)
        paddleocr_cache_dir = await run_in_threadpool(paddleocr_models_dir)

        return GetAIBuddyOnnxCatalogDetail(
            embedding=[GetAIBuddyOnnxOptionDetail(**item) for item in embedding],
            ocr=[GetAIBuddyOnnxOptionDetail(**item) for item in ocr],
            paddleocr=[GetAIBuddyOnnxOptionDetail(**item) for item in paddleocr],
            cache_dir=str(cache_dir),
            ocr_cache_dir=str(ocr_cache_dir),
            paddleocr_cache_dir=str(paddleocr_cache_dir),
        )

    @staticmethod
    async def download_onnx_model(*, model_id: str) -> GetAIBuddyOnnxDownloadStatusDetail:
        """
        调度本地 ONNX 向量模型下载

        :param model_id: 模型 ID
        :return:
        """
        data = await run_in_threadpool(start_onnx_download, model_id)
        return GetAIBuddyOnnxDownloadStatusDetail(**data)

    @staticmethod
    async def get_onnx_download_status() -> GetAIBuddyOnnxDownloadStatusDetail:
        """获取本地 ONNX 向量模型下载状态"""
        data = await run_in_threadpool(get_onnx_download_status)
        return GetAIBuddyOnnxDownloadStatusDetail(**data)

    @staticmethod
    async def download_ocr_onnx_model(*, model_id: str) -> GetAIBuddyOnnxDownloadStatusDetail:
        """
        调度本地 ONNX OCR 模型下载

        :param model_id: 模型 ID
        :return:
        """
        data = await run_in_threadpool(start_ocr_onnx_download, model_id)
        return GetAIBuddyOnnxDownloadStatusDetail(**data)

    @staticmethod
    async def get_ocr_onnx_download_status() -> GetAIBuddyOnnxDownloadStatusDetail:
        """获取本地 ONNX OCR 模型下载状态"""
        data = await run_in_threadpool(get_ocr_onnx_download_status)
        return GetAIBuddyOnnxDownloadStatusDetail(**data)

    @staticmethod
    async def download_paddleocr_model(*, model_id: str) -> GetAIBuddyOnnxDownloadStatusDetail:
        """
        调度本机 PaddleOCR 模型下载

        :param model_id: 模型 ID
        :return:
        """
        data = await run_in_threadpool(start_paddleocr_download, model_id)
        return GetAIBuddyOnnxDownloadStatusDetail(**data)

    @staticmethod
    async def get_paddleocr_download_status() -> GetAIBuddyOnnxDownloadStatusDetail:
        """获取本机 PaddleOCR 模型下载状态"""
        data = await run_in_threadpool(get_paddleocr_download_status)
        return GetAIBuddyOnnxDownloadStatusDetail(**data)

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyKnowledgeBase]:
        """
        获取当前用户所有知识库

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await ai_buddy_knowledge_base_dao.get_all(db, user_id)

    @staticmethod
    async def get_mine_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyKnowledgeBase]:
        """
        获取当前用户自己创建的全部知识库

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await ai_buddy_knowledge_base_dao.get_all_owned(db, user_id)

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False) -> AIBuddyKnowledgeBase:
        """
        获取知识库详情

        :param db: 数据库会话
        :param pk: 知识库 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        knowledge_base = await ai_buddy_knowledge_base_dao.get_visible(
            db, pk, user_id=user_id, is_superuser=is_superuser
        )
        if knowledge_base is None:
            raise errors.NotFoundError(msg='知识库不存在')
        return knowledge_base

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        name: str | None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """
        获取知识库列表

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 知识库名称
        :param is_superuser: 是否为超级管理员
        :return:
        """
        knowledge_base_select = await ai_buddy_knowledge_base_dao.get_select(
            None if is_superuser else user_id,
            name,
        )
        return await paging_data(db, knowledge_base_select)

    async def create(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        obj: CreateAIBuddyKnowledgeBaseParam,
    ) -> AIBuddyKnowledgeBase:
        """
        创建知识库

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param obj: 创建参数
        :return:
        """
        obj = self._normalize(obj=obj)
        await load_ai_buddy_config(db, reindex_on_change=False)
        await ai_buddy_knowledge_service.resolve_embed_binding(
            db=db,
            user_id=user_id,
            provider_id=obj.provider_id,
            model_id=obj.model_id,
        )
        if await ai_buddy_knowledge_base_dao.get_by_name(db, user_id, obj.name):
            raise errors.ConflictError(msg='知识库名称已存在')
        return await ai_buddy_knowledge_base_dao.create(db, user_id, obj)

    async def update(
        self,
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
        obj: UpdateAIBuddyKnowledgeBaseParam,
        is_superuser: bool = False,
    ) -> int:
        """
        更新知识库

        :param db: 数据库会话
        :param pk: 知识库 ID
        :param user_id: 用户 ID
        :param obj: 更新参数
        :param is_superuser: 是否为超级管理员
        :return:
        """
        knowledge_base = await self.get(db=db, pk=pk, user_id=user_id, is_superuser=is_superuser)
        if knowledge_base.user_id == SYSTEM_OWNER_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统内置知识库不允许修改')
        obj = self._normalize(obj=obj)
        await load_ai_buddy_config(db, reindex_on_change=False)
        await ai_buddy_knowledge_service.resolve_embed_binding(
            db=db,
            user_id=knowledge_base.user_id,
            provider_id=obj.provider_id,
            model_id=obj.model_id,
        )
        existed = await ai_buddy_knowledge_base_dao.get_by_name(db, knowledge_base.user_id, obj.name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='知识库名称已存在')

        binding_changed = knowledge_base.provider_id != obj.provider_id or knowledge_base.model_id != obj.model_id
        count = await ai_buddy_knowledge_base_dao.update(db, pk, obj)
        if count > 0 and binding_changed:
            await ai_buddy_knowledge_service.reindex_all(db=db, knowledge_base_id=pk, only_changed=True)
        return count

    async def delete(self, *, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False) -> int:
        """
        删除知识库及其文档

        :param db: 数据库会话
        :param pk: 知识库 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        knowledge_base = await self.get(db=db, pk=pk, user_id=user_id, is_superuser=is_superuser)
        if knowledge_base.user_id == SYSTEM_OWNER_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统内置知识库不允许删除')

        documents = await ai_buddy_knowledge_dao.get_all(db, pk)
        for document in documents:
            await ai_buddy_knowledge_service.delete(db=db, pk=document.id)
        return await ai_buddy_knowledge_base_dao.delete(db, pk)

    @staticmethod
    def _normalize(
        *, obj: CreateAIBuddyKnowledgeBaseParam | UpdateAIBuddyKnowledgeBaseParam
    ) -> CreateAIBuddyKnowledgeBaseParam | UpdateAIBuddyKnowledgeBaseParam:
        """
        规范化知识库字段

        :param obj: 创建或更新参数
        :return:
        """
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='知识库名称不能为空')
        description = obj.description.strip() if obj.description else None
        model_id = obj.model_id.strip() if obj.model_id else None
        return obj.model_copy(update={'name': name, 'description': description or None, 'model_id': model_id})


ai_buddy_knowledge_base_service: AIBuddyKnowledgeBaseService = AIBuddyKnowledgeBaseService()
