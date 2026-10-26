import uuid

from collections.abc import Sequence
from hashlib import sha256
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Range,
    VectorParams,
)

from backend.common.log import log
from backend.core.conf import settings

_POINT_NS = uuid.UUID('6b0c0c5e-2f3a-4d7e-9c11-8a1b4e6d7f20')
_client: AsyncQdrantClient | None = None


def _is_memory_qdrant() -> bool:
    url = settings.AI_BUDDY_QDRANT_URL.strip()
    return not url or url == ':memory:'


def _get_qdrant_client() -> AsyncQdrantClient:
    """获取 Qdrant 客户端，空地址时使用内存实例"""
    global _client
    if _client is not None:
        return _client
    if _is_memory_qdrant():
        _client = AsyncQdrantClient(location=':memory:')
    else:
        api_key = settings.AI_BUDDY_QDRANT_API_KEY.strip() or None
        _client = AsyncQdrantClient(url=settings.AI_BUDDY_QDRANT_URL.strip(), api_key=api_key)
    return _client


def knowledge_collection_name(*, provider_id: int | None, model_id: str | None) -> str:
    """
    按向量模型隔离 Qdrant 集合，避免维度混用

    :param provider_id: 供应商 ID
    :param model_id: 模型 ID
    :return:
    """
    selected = (model_id or '').strip()
    base = settings.AI_BUDDY_QDRANT_COLLECTION.strip() or 'ai_buddy_knowledge'
    if not selected:
        return f'{base}_unbound'
    slug = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in selected)[:48]
    source = 'onnx' if provider_id is None else str(provider_id)
    digest = sha256(selected.encode()).hexdigest()[:24]
    return f'{base}_{source}_{slug}_{digest}'


def _knowledge_point_id(knowledge_id: int, chunk_index: int) -> str:
    """
    生成知识切片的稳定点 ID

    :param knowledge_id: 知识 ID
    :param chunk_index: 切片序号
    :return:
    """
    return str(uuid.uuid5(_POINT_NS, f'{knowledge_id}:{chunk_index}'))


async def _ensure_collection(vector_size: int, *, collection_name: str, rebuild: bool = True) -> None:
    """
    确保知识集合存在且向量维度匹配

    :param vector_size: 向量维度
    :param collection_name: 集合名称
    :param rebuild: 维度不匹配时是否删除重建，False 时抛错以避免丢失数据
    :return:
    """
    client = _get_qdrant_client()
    if await client.collection_exists(collection_name):
        info = await client.get_collection(collection_name)
        vectors = info.config.params.vectors
        size = getattr(vectors, 'size', None)
        current_size = int(size) if isinstance(size, int) else None
        if current_size == vector_size:
            return
        if not rebuild:
            raise ValueError(f'Qdrant 集合维度不匹配，请重建索引: {current_size} != {vector_size}')
        log.warning(f'Qdrant 集合维度不匹配，将重建: {current_size} -> {vector_size}')
        await client.delete_collection(collection_name)
    try:
        await client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
    except (UnexpectedResponse, ValueError) as exc:
        already_exists = (
            exc.status_code in (400, 409) and 'already exists' in exc.content.decode(errors='replace').lower()
            if isinstance(exc, UnexpectedResponse)
            else str(exc) == f'Collection {collection_name} already exists'
        )
        if not already_exists or not await client.collection_exists(collection_name):
            raise
        info = await client.get_collection(collection_name)
        current_size = getattr(info.config.params.vectors, 'size', None)
        if current_size != vector_size:
            raise ValueError(f'Qdrant 集合并发创建时维度不匹配: {current_size} != {vector_size}') from exc
    if _is_memory_qdrant():
        return
    await client.create_payload_index(
        collection_name=collection_name,
        field_name='knowledge_id',
        field_schema=PayloadSchemaType.INTEGER,
    )


async def delete_knowledge_points(*, knowledge_id: int, collection_name: str) -> None:
    """
    删除一条知识在 Qdrant 中的切片

    :param knowledge_id: 知识 ID
    :param collection_name: 集合名称
    :return:
    """
    client = _get_qdrant_client()
    if not await client.collection_exists(collection_name):
        return
    await client.delete(
        collection_name=collection_name,
        points_selector=Filter(must=[FieldCondition(key='knowledge_id', match=MatchValue(value=knowledge_id))]),
    )


async def upsert_knowledge_chunks(
    *,
    knowledge_id: int,
    title: str,
    source: str | None,
    chunks: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    collection_name: str,
) -> None:
    """
    写入知识切片向量

    :param knowledge_id: 知识 ID
    :param title: 知识标题
    :param source: 知识来源
    :param chunks: 切片文本
    :param embeddings: 切片向量
    :param collection_name: 集合名称
    :return:
    """
    if not chunks:
        await delete_knowledge_points(knowledge_id=knowledge_id, collection_name=collection_name)
        return
    if len(chunks) != len(embeddings):
        raise ValueError('知识切片与向量数量不一致')
    await _ensure_collection(len(embeddings[0]), collection_name=collection_name)
    points = [
        PointStruct(
            id=_knowledge_point_id(knowledge_id, index),
            vector=list(embeddings[index]),
            payload={
                'knowledge_id': knowledge_id,
                'chunk_index': index,
                'title': title,
                'source': source,
                'content': chunk,
            },
        )
        for index, chunk in enumerate(chunks)
    ]
    client = _get_qdrant_client()
    await client.upsert(collection_name=collection_name, points=points)
    await client.delete(
        collection_name=collection_name,
        points_selector=Filter(
            must=[
                FieldCondition(key='knowledge_id', match=MatchValue(value=knowledge_id)),
                FieldCondition(key='chunk_index', range=Range(gte=len(chunks))),
            ]
        ),
    )


async def search_knowledge_points(
    *,
    query_vector: Sequence[float],
    limit: int,
    collection_name: str,
    knowledge_ids: Sequence[int],
) -> list[dict[str, Any]]:
    """
    按向量检索可见知识切片

    :param query_vector: 查询向量
    :param limit: 返回条数
    :param collection_name: 集合名称
    :param knowledge_ids: 可见知识文档 ID
    :return:
    """
    if not knowledge_ids:
        return []
    client = _get_qdrant_client()
    if not await client.collection_exists(collection_name):
        return []
    response = await client.query_points(
        collection_name=collection_name,
        query=list(query_vector),
        query_filter=Filter(must=[FieldCondition(key='knowledge_id', match=MatchAny(any=list(knowledge_ids)))]),
        limit=limit,
        with_payload=True,
    )
    hits: list[dict[str, Any]] = []
    for point in response.points:
        payload = point.payload or {}
        hits.append({
            'knowledge_id': payload.get('knowledge_id'),
            'title': payload.get('title') or '',
            'source': payload.get('source'),
            'content': payload.get('content') or '',
            'score': float(point.score or 0),
        })
    return hits


async def list_indexed_knowledge_ids(*, collection_name: str) -> set[int]:
    """
    列出已索引的知识 ID

    :param collection_name: 集合名称
    :return:
    """
    client = _get_qdrant_client()
    if not await client.collection_exists(collection_name):
        return set()
    indexed: set[int] = set()
    offset: Any = None
    while True:
        records, offset = await client.scroll(
            collection_name=collection_name,
            limit=256,
            offset=offset,
            with_payload=['knowledge_id'],
            with_vectors=False,
        )
        for record in records:
            payload = record.payload or {}
            knowledge_id = payload.get('knowledge_id')
            if isinstance(knowledge_id, int):
                indexed.add(knowledge_id)
        if offset is None:
            break
    return indexed


def _memory_collection_name() -> str:
    """记忆向量集合，与知识库分开"""
    return settings.AI_BUDDY_QDRANT_MEMORY_COLLECTION.strip() or 'ai_buddy_memory'


def _memory_point_id(path: str) -> str:
    """
    记忆路径的稳定点 ID

    :param path: 文件路径
    :return:
    """
    return str(uuid.uuid5(_POINT_NS, f'memory:{path}'))


async def upsert_memory_vector(*, path: str, content: str, embedding: Sequence[float]) -> None:
    """
    写入一条记忆向量

    :param path: 记忆路径
    :param content: 记忆内容
    :param embedding: 向量
    :return:
    """
    collection = _memory_collection_name()
    await _ensure_collection(len(embedding), collection_name=collection, rebuild=False)
    await _get_qdrant_client().upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=_memory_point_id(path),
                vector=list(embedding),
                payload={'path': path, 'owner': path.partition('/')[0], 'content': content[:2000]},
            )
        ],
    )


async def delete_memory_vector(*, path: str) -> None:
    """
    删除一条记忆向量

    :param path: 文件路径
    :return:
    """
    collection = _memory_collection_name()
    client = _get_qdrant_client()
    if not await client.collection_exists(collection):
        return
    await client.delete(
        collection_name=collection,
        points_selector=Filter(must=[FieldCondition(key='path', match=MatchValue(value=path))]),
    )


async def search_memory_points(*, query_vector: Sequence[float], prefix: str, limit: int) -> list[dict[str, Any]]:
    """
    按向量检索记忆

    :param query_vector: 查询向量
    :param prefix: 路径前缀
    :param limit: 条数
    :return:
    """
    collection = _memory_collection_name()
    client = _get_qdrant_client()
    if not await client.collection_exists(collection):
        return []
    # 按路径首段（用户）在服务端缩小范围，再按完整前缀精确过滤，避免 limit 被其他用户的结果占满
    owner = prefix.partition('/')[0] if '/' in prefix else ''
    response = await client.query_points(
        collection_name=collection,
        query=list(query_vector),
        query_filter=Filter(must=[FieldCondition(key='owner', match=MatchValue(value=owner))]) if owner else None,
        limit=limit,
        with_payload=True,
    )
    hits: list[dict[str, Any]] = []
    for point in response.points:
        payload = point.payload or {}
        path = str(payload.get('path') or '')
        if prefix and not path.startswith(prefix):
            continue
        hits.append({'path': path, 'content': payload.get('content') or '', 'score': float(point.score or 0)})
    return hits
