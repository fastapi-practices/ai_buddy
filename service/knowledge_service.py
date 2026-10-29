import asyncio

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from fastapi import UploadFile
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction
from starlette.concurrency import run_in_threadpool

from backend.common.exception import errors
from backend.common.log import log
from backend.common.pagination import paging_data
from backend.core.conf import settings
from backend.plugin.ai_buddy.crud.crud_knowledge import ai_buddy_knowledge_dao, knowledge_visibility_context
from backend.plugin.ai_buddy.crud.crud_knowledge_base import ai_buddy_knowledge_base_dao
from backend.plugin.ai_buddy.crud.crud_model import ai_buddy_model_dao
from backend.plugin.ai_buddy.crud.crud_provider import ai_buddy_provider_dao
from backend.plugin.ai_buddy.enums import (
    AIBuddyModelKind,
    AIBuddyModelModality,
    AIBuddyObjectKind,
    AIBuddyObjectLocation,
    AIBuddyOcrBackend,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.model import AIBuddyKnowledge
from backend.plugin.ai_buddy.provider.base import normalize_provider_api_host
from backend.plugin.ai_buddy.schema.knowledge import CreateAIBuddyKnowledgeParam
from backend.plugin.ai_buddy.service.default_model_service import ai_buddy_default_model_service
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config
from backend.plugin.ai_buddy.utils.knowledge_ocr import (
    join_ocr_segments,
    ocr_images_with_mistral,
    ocr_images_with_onnx,
    ocr_images_with_paddleocr,
    ocr_images_with_system,
    resolve_ocr_backend,
)
from backend.plugin.ai_buddy.utils.knowledge_parser import parse_knowledge_uploads
from backend.plugin.ai_buddy.utils.model_catalog import require_model_kind
from backend.plugin.ai_buddy.utils.object_key import build_knowledge_key
from backend.plugin.ai_buddy.utils.onnx_embed import embed_onnx_texts, require_onnx_model_downloaded
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID
from backend.plugin.ai_buddy.utils.qdrant_store import (
    delete_knowledge_points,
    knowledge_collection_name,
    list_indexed_knowledge_ids,
    search_knowledge_points,
    upsert_knowledge_chunks,
)
from backend.plugin.ai_buddy.utils.text_vector import split_chunks
from backend.plugin.s3.utils.text_store import read_text, require_storage, write_text


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    """知识检索命中"""

    knowledge_id: int
    title: str
    source: str | None
    content: str
    score: float


class AIBuddyKnowledgeService:
    """AI 知识服务类"""

    @staticmethod
    async def resolve_embed_binding(
        *,
        db: AsyncSession,
        user_id: int,
        provider_id: int | None,
        model_id: str | None,
    ) -> tuple[int | None, str | None]:
        """
        解析向量模型，知识库未指定时使用 RAG 配置的本地模型或默认远程模型

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param provider_id: 供应商 ID
        :param model_id: 模型 ID
        :return:
        """
        selected_model = (model_id or '').strip() or None
        if provider_id is None and selected_model:
            return None, require_onnx_model_downloaded(selected_model)
        if (provider_id is None) != (selected_model is None):
            raise errors.RequestError(msg='向量化供应商和模型需要同时指定')
        if provider_id is None:
            if settings.AI_BUDDY_EMBEDDING_BACKEND == 'onnx':
                return None, require_onnx_model_downloaded(settings.AI_BUDDY_ONNX_EMBEDDING_MODEL)
            default = await ai_buddy_default_model_service.get_enabled_or_none(
                db=db,
                kind=AIBuddyModelKind.embedding,
            )
            if default is None:
                raise errors.RequestError(msg='请先配置默认向量模型')
            return default.provider_id, default.model_id
        provider = await ai_buddy_provider_dao.get_visible(db, provider_id, user_id)
        if not provider:
            raise errors.NotFoundError(msg='向量化供应商不存在')
        if not provider.status:
            raise errors.RequestError(msg='向量化供应商已停用')
        model = await ai_buddy_model_dao.get_by_model_and_provider(db, selected_model, provider_id)
        if not model:
            raise errors.NotFoundError(msg='向量化模型不存在')
        if not model.status:
            raise errors.RequestError(msg='向量化模型已停用')
        require_model_kind(model, AIBuddyModelKind.embedding, msg='向量化请选择向量模型')
        return provider_id, selected_model

    @staticmethod
    async def _embed_texts(  # ruff: ignore[complex-structure]
        *,
        db: AsyncSession,
        texts: Sequence[str],
        provider_id: int | None,
        model_id: str | None,
    ) -> list[list[float]]:
        """
        用指定供应商模型生成文本向量

        :param db: 数据库会话
        :param texts: 文本列表
        :param provider_id: 供应商 ID
        :param model_id: 模型 ID
        :return:
        """
        if not texts:
            return []
        if provider_id is None:
            return await run_in_threadpool(embed_onnx_texts, model_id or '', texts)
        if not model_id:
            raise errors.RequestError(msg='请先配置默认向量模型')
        provider = await ai_buddy_provider_dao.get(db, provider_id)
        if not provider or not provider.status:
            raise errors.RequestError(msg='向量化供应商不可用')
        if not provider.api_key.strip() or not provider.api_host.strip():
            raise errors.RequestError(msg='向量化供应商缺少接口地址或密钥')

        try:
            host = normalize_provider_api_host(AIBuddyProviderType(provider.type), provider.api_host)
            multimodal = host.endswith('/embeddings/multimodal') or model_id.lower().startswith(
                'doubao-embedding-vision'
            )
            url = host if host.endswith(('/embeddings', '/embeddings/multimodal')) else f'{host}/embeddings'
            if multimodal and not url.endswith('/multimodal'):
                url += '/multimodal'
            async with httpx.AsyncClient(timeout=30) as client:
                headers = {'Authorization': f'Bearer {provider.api_key.strip()}'}
                if not multimodal:
                    response = await client.post(url, headers=headers, json={'model': model_id, 'input': list(texts)})
                    error_text = response.text.lower() if response.status_code == 400 else ''
                    if response.status_code == 400 and (
                        '/embeddings/multimodal' in error_text
                        or ('doubao-embedding-vision' in error_text and 'does not support this api' in error_text)
                    ):
                        multimodal = True
                        url += '/multimodal'
                    else:
                        response.raise_for_status()
                        data = response.json().get('data')
                if multimodal:
                    # 多模态接口会融合一次输入为一个向量，切片需要独立请求
                    data = []
                    for text in texts:
                        response = await client.post(
                            url,
                            headers=headers,
                            json={
                                'model': model_id,
                                'input': [{'type': 'text', 'text': text}],
                                'encoding_format': 'float',
                            },
                        )
                        response.raise_for_status()
                        item = response.json().get('data')
                        if not isinstance(item, dict):
                            raise TypeError('多模态嵌入接口返回向量无效')
                        data.append(item)
            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError('嵌入接口返回数量不匹配')
            embeddings: list[list[float]] = []
            for item in sorted(data, key=lambda row: int(row.get('index', 0))):
                vector = item.get('embedding')
                if not isinstance(vector, list) or not vector:
                    raise ValueError('嵌入接口返回向量无效')
                embeddings.append([float(value) for value in vector])
        except Exception as exc:
            log.warning(f'嵌入模型调用失败: {exc}')
            raise errors.RequestError(msg='向量化失败，请检查供应商和模型') from exc
        return embeddings

    async def _index(self, *, db: AsyncSession, knowledge: AIBuddyKnowledge) -> None:
        """
        为一条知识建立切片和向量

        :param db: 数据库会话
        :param knowledge: 知识记录
        :return:
        """
        payload = f'{knowledge.title}\n\n{knowledge.content}'.strip()
        chunks = await run_in_threadpool(
            split_chunks,
            payload,
            chunk_chars=settings.AI_BUDDY_RAG_CHUNK_CHARS,
            overlap=settings.AI_BUDDY_RAG_CHUNK_OVERLAP,
        )
        embeddings = (
            await self._embed_texts(
                db=db,
                texts=chunks,
                provider_id=knowledge.provider_id,
                model_id=knowledge.model_id,
            )
            if chunks
            else []
        )
        await upsert_knowledge_chunks(
            knowledge_id=knowledge.id,
            title=knowledge.title,
            source=knowledge.source,
            chunks=chunks,
            embeddings=embeddings,
            collection_name=knowledge_collection_name(
                provider_id=knowledge.provider_id,
                model_id=knowledge.model_id,
            ),
        )

    async def reindex_all(
        self,
        *,
        db: AsyncSession,
        knowledge_base_id: int | None = None,
        default_only: bool = False,
        only_changed: bool = False,
    ) -> None:
        """
        按当前向量配置重建知识索引

        :param db: 数据库会话
        :param knowledge_base_id: 知识库 ID，空则重建全部
        :param default_only: 是否仅处理继承全局向量配置的知识库
        :param only_changed: 是否跳过实际向量模型未变更的文档
        :return:
        """
        with knowledge_visibility_context(user_id=SYSTEM_OWNER_USER_ID, is_superuser=True):
            knowledge_rows = await ai_buddy_knowledge_dao.get_all(db, knowledge_base_id, default_only=default_only)
            bindings: dict[int, tuple[int | None, str | None]] = {}
            for knowledge in knowledge_rows:
                if knowledge.knowledge_base_id not in bindings:
                    knowledge_base = await ai_buddy_knowledge_base_dao.get(db, knowledge.knowledge_base_id)
                    if knowledge_base is None:
                        continue
                    if default_only and (knowledge_base.provider_id is not None or knowledge_base.model_id is not None):
                        continue
                    bindings[knowledge.knowledge_base_id] = await self.resolve_embed_binding(
                        db=db,
                        user_id=knowledge_base.user_id,
                        provider_id=knowledge_base.provider_id,
                        model_id=knowledge_base.model_id,
                    )
                provider_id, model_id = bindings[knowledge.knowledge_base_id]
                if only_changed and (knowledge.provider_id, knowledge.model_id) == (provider_id, model_id):
                    continue
                knowledge.provider_id = provider_id
                knowledge.model_id = model_id
                if knowledge.object_key:
                    knowledge.content = await read_text(
                        db=db, key=knowledge.object_key, storage_id=knowledge.storage_id
                    )
                await self._index(db=db, knowledge=knowledge)

    @staticmethod
    async def get_all(
        *,
        db: AsyncSession,
        user_id: int,
        knowledge_base_id: int | None = None,
        include_content: bool = True,
        is_superuser: bool = False,
    ) -> Sequence[AIBuddyKnowledge]:
        """
        获取知识文档

        :param db: 数据库会话
        :param user_id: 当前用户 ID
        :param knowledge_base_id: 知识库 ID
        :param include_content: 是否从对象存储读取正文
        :param is_superuser: 是否为后台超级管理员
        :return:
        """
        if knowledge_base_id is not None:
            from backend.plugin.ai_buddy.service.knowledge_base_service import ai_buddy_knowledge_base_service

            await ai_buddy_knowledge_base_service.get(
                db=db, pk=knowledge_base_id, user_id=user_id, is_superuser=is_superuser
            )
        knowledge_rows = await ai_buddy_knowledge_dao.get_all_visible(
            db, knowledge_base_id, user_id=user_id, is_superuser=is_superuser
        )
        for knowledge in knowledge_rows:
            if include_content:
                knowledge.content = await read_text(db=db, key=knowledge.object_key, storage_id=knowledge.storage_id)
            else:
                knowledge.content = ''
        return knowledge_rows

    @staticmethod
    async def get(
        *, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False, knowledge_base_id: int | None = None
    ) -> AIBuddyKnowledge:
        """
        获取知识详情

        :param db: 数据库会话
        :param pk: 知识 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为后台超级管理员
        :param knowledge_base_id: 限定所属知识库 ID
        :return:
        """
        if knowledge_base_id is not None:
            from backend.plugin.ai_buddy.service.knowledge_base_service import ai_buddy_knowledge_base_service

            await ai_buddy_knowledge_base_service.get(
                db=db, pk=knowledge_base_id, user_id=user_id, is_superuser=is_superuser
            )
        knowledge = await ai_buddy_knowledge_dao.get_visible(db, pk, user_id=user_id, is_superuser=is_superuser)
        if knowledge is None or (knowledge_base_id is not None and knowledge.knowledge_base_id != knowledge_base_id):
            raise errors.NotFoundError(msg='知识不存在')
        knowledge.content = await read_text(db=db, key=knowledge.object_key, storage_id=knowledge.storage_id)
        return knowledge

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        title: str | None,
        knowledge_base_id: int | None = None,
        include_content: bool = True,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """
        获取知识文档列表

        :param db: 数据库会话
        :param user_id: 当前用户 ID
        :param title: 知识标题
        :param knowledge_base_id: 知识库 ID
        :param include_content: 是否从对象存储读取正文
        :param is_superuser: 是否为后台超级管理员
        :return:
        """
        if knowledge_base_id is not None:
            from backend.plugin.ai_buddy.service.knowledge_base_service import ai_buddy_knowledge_base_service

            await ai_buddy_knowledge_base_service.get(
                db=db, pk=knowledge_base_id, user_id=user_id, is_superuser=is_superuser
            )
        knowledge_select = await ai_buddy_knowledge_dao.get_visible_select(
            db, title, knowledge_base_id, user_id=user_id, is_superuser=is_superuser
        )
        page_data = await paging_data(db, knowledge_select)
        for item in page_data.get('items') or []:
            if include_content:
                item['content'] = await read_text(db=db, key=item.get('object_key'), storage_id=item.get('storage_id'))
            else:
                item['content'] = ''
        return page_data

    async def create(  # ruff: ignore[complex-structure]
        self,
        *,
        db: AsyncSession,
        user_id: int,
        files: Sequence[UploadFile],
        knowledge_base_id: int,
        title: str | None = None,
        provider_id: int | None = None,
        model_id: str | None = None,
        is_superuser: bool = False,
        allow_system: bool = False,
    ) -> None:
        """
        上传并创建知识文档

        :param db: 数据库会话
        :param user_id: 上传用户 ID
        :param files: 知识文件、目录或包含文档的 zip
        :param knowledge_base_id: 知识库 ID
        :param title: 知识标题，仅单个文件时生效，空值使用文件名
        :param provider_id: 向量化供应商 ID
        :param model_id: 向量化模型 ID
        :param is_superuser: 是否为超级管理员
        :param allow_system: 后台写入是否允许系统知识库
        :return:
        """
        knowledge_base = await ai_buddy_knowledge_base_dao.get(db, knowledge_base_id)
        if knowledge_base is None:
            raise errors.NotFoundError(msg='知识库不存在')
        self._assert_can_write_knowledge_base(
            owner_id=knowledge_base.user_id,
            user_id=user_id,
            is_superuser=is_superuser,
            allow_system=allow_system,
        )
        await load_ai_buddy_config(db)
        embed_provider_id, embed_model_id = await self.resolve_embed_binding(
            db=db,
            user_id=knowledge_base.user_id,
            provider_id=provider_id if provider_id is not None else knowledge_base.provider_id,
            model_id=model_id if model_id is not None else knowledge_base.model_id,
        )
        payloads = [(item.filename, await item.read()) for item in files]
        documents = await run_in_threadpool(parse_knowledge_uploads, files=payloads, title=title)
        for uploaded in documents:
            backend = resolve_ocr_backend()
            images = [item for item in uploaded.segments if item.image]
            content = uploaded.content
            if not images:
                if not content:
                    raise errors.RequestError(msg='知识内容不能为空')
            else:
                if backend == AIBuddyOcrBackend.system:
                    texts = await run_in_threadpool(ocr_images_with_system, images)
                elif backend == AIBuddyOcrBackend.paddleocr:
                    texts = await run_in_threadpool(ocr_images_with_paddleocr, images)
                elif backend == AIBuddyOcrBackend.onnx:
                    texts = await run_in_threadpool(ocr_images_with_onnx, images)
                elif backend == AIBuddyOcrBackend.mistral:
                    texts = await run_in_threadpool(ocr_images_with_mistral, images)
                elif backend == AIBuddyOcrBackend.vision:
                    from pydantic_ai import Agent
                    from pydantic_ai.messages import BinaryContent

                    from backend.plugin.ai_buddy.provider.registry import get_provider_adapter
                    from backend.plugin.ai_buddy.utils.http_client import build_retry_http_client

                    default = await ai_buddy_default_model_service.get_enabled_or_none(
                        db=db, kind=AIBuddyModelKind.chat
                    )
                    if default is None:
                        raise errors.RequestError(msg='视觉 OCR 需要先配置默认对话模型')
                    model = await ai_buddy_model_dao.get_by_model_and_provider(
                        db, default.model_id, default.provider_id
                    )
                    if model is None:
                        raise errors.RequestError(msg='视觉 OCR 使用的默认对话模型不存在')
                    if AIBuddyModelModality.image not in (model.input_modalities or []):
                        raise errors.RequestError(msg='视觉 OCR 需要默认对话模型支持图片输入')
                    provider = await ai_buddy_provider_dao.get(db, default.provider_id)
                    if provider is None or not provider.status:
                        raise errors.RequestError(msg='视觉 OCR 使用的默认供应商不可用')
                    if not provider.api_key.strip() or not provider.api_host.strip():
                        raise errors.RequestError(msg='视觉 OCR 使用的默认供应商缺少接口地址或密钥')

                    http_client = build_retry_http_client()

                    try:
                        adapter = get_provider_adapter(provider.type)
                        vision_model = adapter.create_model(
                            model_name=default.model_id,
                            api_key=provider.api_key,
                            base_url=provider.api_host,
                            http_client=http_client,
                        )
                        agent: Agent[None, str] = Agent(
                            vision_model,
                            instructions='提取图片中的全部文字，只返回文字本身，不要解释、翻译或添加说明',
                            output_type=str,
                        )
                        texts = [
                            str(
                                (
                                    await agent.run([
                                        '请提取文字',
                                        BinaryContent(data=item.image, media_type=item.media_type or 'image/png'),
                                    ])
                                ).output
                                or ''
                            ).strip()
                            if item.image
                            else ''
                            for item in images
                        ]
                    except errors.RequestError:
                        raise
                    except Exception as exc:
                        raise errors.RequestError(msg='视觉 OCR 失败，请检查默认对话模型') from exc
                    finally:
                        if not http_client.is_closed:
                            await http_client.aclose()
                else:
                    raise errors.RequestError(msg='OCR 后端无效')
                content = join_ocr_segments(uploaded.segments, texts)

            knowledge = await ai_buddy_knowledge_dao.create(
                db,
                knowledge_base.user_id,
                CreateAIBuddyKnowledgeParam(
                    title=uploaded.title,
                    source=uploaded.source,
                    knowledge_base_id=knowledge_base_id,
                    file_type=uploaded.file_type,
                    provider_id=embed_provider_id,
                    model_id=embed_model_id,
                ),
            )
            object_key = build_knowledge_key(pk=knowledge.id)
            storage = await require_storage(db=db)
            await write_text(db=db, key=object_key, content=content, storage_id=storage.id)
            knowledge.object_key = object_key
            knowledge.storage_id = storage.id
            knowledge.content = content
            await db.flush()
            await self._track_object(db=db, knowledge=knowledge, content=content, released=False)
            try:
                await self._index(db=db, knowledge=knowledge)
            except Exception as exc:
                log.warning(f'知识索引失败 knowledge_id={knowledge.id}: {exc}')

    @staticmethod
    async def _track_object(
        *, db: AsyncSession, knowledge: AIBuddyKnowledge, content: str | None, released: bool
    ) -> None:
        """
        同步知识正文与统一对象的引用，删除时只释放引用，由回收任务在宽限期后清理对象

        :param db: 数据库会话
        :param knowledge: 知识记录
        :param content: 本次写入的正文，未写入时为空
        :param released: 是否释放引用
        :return:
        """
        if not knowledge.object_key or knowledge.storage_id is None:
            return
        stored = await ai_buddy_object_service.register(
            db=db,
            user_id=knowledge.user_id,
            kind=AIBuddyObjectKind.knowledge,
            location=AIBuddyObjectLocation.s3,
            object_key=knowledge.object_key,
            storage_id=knowledge.storage_id,
            size=len(content.encode()) if content is not None else None,
            mime_type='text/plain',
        )
        track = ai_buddy_object_service.remove_reference if released else ai_buddy_object_service.add_reference
        await track(db=db, obj=stored, owner_type='knowledge', owner_id=str(knowledge.id), actor_id=None)

    @staticmethod
    def _assert_can_write_knowledge_base(
        *,
        owner_id: int,
        user_id: int,
        is_superuser: bool,
        allow_system: bool,
    ) -> None:
        """
        校验当前用户是否可写入该知识库

        :param owner_id: 知识库归属用户 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为超级管理员
        :param allow_system: 后台写入是否允许系统知识库
        :return:
        """
        if owner_id == user_id or is_superuser:
            return
        if allow_system and owner_id == SYSTEM_OWNER_USER_ID:
            return
        raise errors.NotFoundError(msg='知识库不存在')

    async def delete(
        self,
        *,
        db: AsyncSession,
        pk: int,
        user_id: int | None = None,
        knowledge_base_id: int | None = None,
        is_superuser: bool = False,
        allow_system: bool = False,
    ) -> int:
        """
        删除知识

        :param db: 数据库会话
        :param pk: 知识 ID
        :param user_id: 当前用户 ID，空则跳过归属校验
        :param knowledge_base_id: 限定所属知识库 ID
        :param is_superuser: 是否为超级管理员
        :param allow_system: 后台写入是否允许系统知识库
        :return:
        """
        if knowledge_base_id is not None:
            from backend.plugin.ai_buddy.service.knowledge_base_service import ai_buddy_knowledge_base_service

            await ai_buddy_knowledge_base_service.get(
                db=db,
                pk=knowledge_base_id,
                user_id=user_id if user_id is not None else SYSTEM_OWNER_USER_ID,
                is_superuser=is_superuser or user_id is None,
            )
        knowledge = (
            await ai_buddy_knowledge_dao.get_visible(db, pk, user_id=user_id, is_superuser=is_superuser)
            if knowledge_base_id is not None and user_id is not None
            else await ai_buddy_knowledge_dao.get(db, pk)
        )
        if knowledge_base_id is not None and (knowledge is None or knowledge.knowledge_base_id != knowledge_base_id):
            raise errors.NotFoundError(msg='知识不存在')
        if knowledge is not None and user_id is not None:
            knowledge_base = await ai_buddy_knowledge_base_dao.get(db, knowledge.knowledge_base_id)
            if knowledge_base is None:
                raise errors.NotFoundError(msg='知识不存在')
            self._assert_can_write_knowledge_base(
                owner_id=knowledge_base.user_id,
                user_id=user_id,
                is_superuser=is_superuser,
                allow_system=allow_system,
            )
        if knowledge is not None:
            await self._track_object(db=db, knowledge=knowledge, content=None, released=True)
        count = await ai_buddy_knowledge_dao.delete(db, pk)
        if count > 0:
            try:
                await load_ai_buddy_config(db)
                collection = knowledge_collection_name(
                    provider_id=knowledge.provider_id if knowledge is not None else None,
                    model_id=knowledge.model_id if knowledge is not None else None,
                )
                await delete_knowledge_points(knowledge_id=pk, collection_name=collection)
            except Exception as exc:
                log.warning(f'知识索引删除失败 knowledge_id={pk}: {exc}')
        return count

    async def search(  # ruff: ignore[complex-structure]
        self,
        *,
        db: AsyncSession,
        user_id: int,
        query: str,
        top_k: int | None = None,
    ) -> list[KnowledgeHit]:
        """
        按语义检索知识切片

        :param db: 数据库会话
        :param user_id: 当前用户 ID
        :param query: 查询文本
        :param top_k: 返回条数
        :return:
        """
        keyword = query.strip()
        if not keyword:
            return []

        await load_ai_buddy_config(db)
        knowledge_rows = await ai_buddy_knowledge_dao.get_all_visible(db, user_id=user_id)
        indexed_by_collection: dict[str, set[int]] = {}
        for knowledge in knowledge_rows:
            collection = knowledge_collection_name(provider_id=knowledge.provider_id, model_id=knowledge.model_id)
            if collection not in indexed_by_collection:
                indexed_by_collection[collection] = await list_indexed_knowledge_ids(
                    collection_name=collection,
                )
            if knowledge.id not in indexed_by_collection[collection]:
                knowledge.content = await read_text(db=db, key=knowledge.object_key, storage_id=knowledge.storage_id)
                await self._index(db=db, knowledge=knowledge)

        knowledge_rows = await ai_buddy_knowledge_dao.get_all_visible(db, user_id=user_id)
        groups: dict[tuple[int | None, str | None], list[int]] = {}
        for knowledge in knowledge_rows:
            groups.setdefault((knowledge.provider_id, knowledge.model_id), []).append(knowledge.id)
        limit = top_k if top_k is not None else settings.AI_BUDDY_RAG_TOP_K
        if limit <= 0:
            return []
        points: list[dict[str, Any]] = []
        for (provider_id, model_id), knowledge_ids in groups.items():
            query_vectors = await self._embed_texts(
                db=db,
                texts=[keyword],
                provider_id=provider_id,
                model_id=model_id,
            )
            collection = knowledge_collection_name(provider_id=provider_id, model_id=model_id)
            collection_points = await search_knowledge_points(
                query_vector=query_vectors[0],
                limit=max(limit * 4, limit),
                collection_name=collection,
                knowledge_ids=knowledge_ids,
            )
            points.extend({**point, 'collection_name': collection} for point in collection_points)

        # 向量索引可能残留已删除或已失去访问权限的文档，返回前重新校验
        visible_rows = await ai_buddy_knowledge_dao.get_all_visible(db, user_id=user_id)
        visible_by_id = {knowledge.id: knowledge for knowledge in visible_rows}
        points.sort(key=lambda item: float(item.get('score') or 0), reverse=True)
        hits: list[KnowledgeHit] = []
        seen: set[int] = set()
        for point in points:
            knowledge_id = point.get('knowledge_id')
            score = float(point.get('score') or 0)
            if type(knowledge_id) is not int or knowledge_id in seen or score <= 0:
                continue
            knowledge = visible_by_id.get(knowledge_id)
            if knowledge is None or point['collection_name'] != knowledge_collection_name(
                provider_id=knowledge.provider_id, model_id=knowledge.model_id
            ):
                continue
            seen.add(knowledge_id)
            hits.append(
                KnowledgeHit(
                    knowledge_id=knowledge_id,
                    title=knowledge.title,
                    source=knowledge.source,
                    content=str(point.get('content') or ''),
                    score=score,
                )
            )
            if len(hits) >= limit:
                break
        return hits

    @staticmethod
    def schedule_reindex(*, db: AsyncSession | None = None) -> None:
        """
        调度知识索引重建，指定会话时等待当前事务提交

        :param db: 默认模型更新使用的数据库会话
        :return:
        """
        if db is not None and db.in_transaction():
            session = db.sync_session
            if not event.contains(session, 'after_commit', _schedule_committed_reindex):
                event.listen(session, 'after_commit', _schedule_committed_reindex)
                event.listen(session, 'after_rollback', _discard_rolled_back_reindex)
                event.listen(session, 'after_transaction_end', _clear_finished_reindex)
            transaction = session.get_nested_transaction() or session.get_transaction()
            if transaction is not None:
                pending: set[SessionTransaction] = session.info.setdefault(_PENDING_REINDEX_KEY, set())
                pending.add(transaction)
                return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_reindex_all_task())


ai_buddy_knowledge_service: AIBuddyKnowledgeService = AIBuddyKnowledgeService()


async def _reindex_all_task() -> None:
    """后台重建默认向量模型变更的知识索引"""
    from backend.database.db import async_db_session

    try:
        async with async_db_session.begin() as db:
            await ai_buddy_knowledge_service.reindex_all(db=db, default_only=True, only_changed=True)
    except Exception as exc:
        log.warning(f'知识索引重建失败: {exc}')


_PENDING_REINDEX_KEY = 'ai_buddy_knowledge_reindex_pending'


def _schedule_committed_reindex(session: Session) -> None:
    """
    最外层事务提交后启动重建，保存点提交只合并请求

    :param session: 事务会话
    :return:
    """
    pending: set[SessionTransaction] | None = session.info.get(_PENDING_REINDEX_KEY)
    if not pending:
        return
    transaction = session.get_nested_transaction()
    if transaction is not None:
        if transaction in pending:
            pending.remove(transaction)
            if transaction.parent is not None:
                pending.add(transaction.parent)
        return
    session.info.pop(_PENDING_REINDEX_KEY, None)
    ai_buddy_knowledge_service.schedule_reindex()


def _discard_rolled_back_reindex(session: Session) -> None:
    """
    丢弃回滚事务内的重建请求

    :param session: 事务会话
    :return:
    """
    transaction = session.get_nested_transaction()
    if transaction is None:
        session.info.pop(_PENDING_REINDEX_KEY, None)
    else:
        pending: set[SessionTransaction] | None = session.info.get(_PENDING_REINDEX_KEY)
        if pending is not None:
            pending.discard(transaction)


def _clear_finished_reindex(session: Session, transaction: SessionTransaction) -> None:
    """
    事务结束后清理请求，避免关闭会话后复用遗留状态

    :param session: 事务会话
    :param transaction: 事务
    :return:
    """
    if transaction.parent is None:
        session.info.pop(_PENDING_REINDEX_KEY, None)
