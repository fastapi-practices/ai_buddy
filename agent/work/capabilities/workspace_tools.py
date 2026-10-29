from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.capabilities import Toolset
from pydantic_ai.toolsets import FunctionToolset

from backend.common.exception import errors
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyArtifactKind, AIBuddyChatGenerationType
from backend.plugin.ai_buddy.schema.artifact import CreateAIBuddyArtifactParam, UpdateAIBuddyArtifactParam
from backend.plugin.ai_buddy.service.artifact_service import ai_buddy_artifact_service
from backend.plugin.ai_buddy.service.knowledge_service import ai_buddy_knowledge_service
from backend.plugin.ai_buddy.service.message_history_service import ai_buddy_message_history_service
from backend.plugin.ai_buddy.service.skill_service import ai_buddy_skill_service

_SNIPPET_CHARS = 240
_KNOWLEDGE_CONTENT_CHARS = 12000
_ARTIFACT_CONTENT_CHARS = 12000


def build_workspace_tools_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    构建知识和产物的检索与读写工具

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.user_id is None:
        return CapabilityResult(capability=None)
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    if not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        return CapabilityResult(capability=None)

    toolset: FunctionToolset[ChatAgentDeps] = FunctionToolset[ChatAgentDeps]()
    toolset.tool(search_knowledge)
    toolset.tool(get_knowledge)
    toolset.tool(read_skill_file)
    toolset.tool(list_artifacts)
    toolset.tool(get_artifact)
    toolset.tool(search_conversation_history)
    if ctx.forwarded_props.agent_mode != AIBuddyAgentMode.chat:
        toolset.tool(write_artifact)
    return CapabilityResult(
        capability=Toolset(toolset),
        introduces_function_tool_source=True,
    )


async def search_knowledge(ctx: RunContext[ChatAgentDeps], query: str) -> str:
    """
    按语义检索知识库，返回最相关切片的 ID、标题和内容

    :param ctx: 运行上下文
    :param query: 检索内容
    :return:
    """
    async with async_db_session() as db:
        hits = await ai_buddy_knowledge_service.search(db=db, query=query, user_id=ctx.deps.user_id)
    if not hits:
        return '未找到匹配知识'
    snippets: list[str] = []
    for item in hits:
        normalized = ' '.join(item.content.split())
        snippet = normalized if len(normalized) <= _SNIPPET_CHARS else f'{normalized[:_SNIPPET_CHARS]}…'
        snippets.append(f'- #{item.knowledge_id} {item.title}（{item.score:.2f}）\n  {snippet}')
    return '匹配知识片段：\n' + '\n'.join(snippets)


async def get_knowledge(ctx: RunContext[ChatAgentDeps], knowledge_id: int) -> str:
    """
    读取一条知识的完整内容

    :param ctx: 运行上下文
    :param knowledge_id: 知识 ID
    :return:
    """
    try:
        async with async_db_session() as db:
            knowledge = await ai_buddy_knowledge_service.get(db=db, pk=knowledge_id, user_id=ctx.deps.user_id)
    except errors.NotFoundError:
        return '知识不存在'
    source = f'\n来源：{knowledge.source}' if knowledge.source else ''
    content = knowledge.content
    if len(content) > _KNOWLEDGE_CONTENT_CHARS:
        content = f'{content[:_KNOWLEDGE_CONTENT_CHARS]}\n…内容已截断'
    return f'## 知识：{knowledge.title}{source}\n\n{content}'


async def read_skill_file(
    ctx: RunContext[ChatAgentDeps], skill_id: int, path: str, offset: int = 0, limit: int = 12000
) -> str:
    """
    读取技能包内相对路径的 UTF-8 文本；offset/limit 按字符分页，脚本只读不执行

    :param ctx: 运行上下文
    :param skill_id: 技能 ID
    :param path: 文件路径
    :param offset: 起始偏移量
    :param limit: 数量上限
    :return:
    """
    try:
        async with async_db_session() as db:
            return await ai_buddy_skill_service.read_file(
                db=db, pk=skill_id, user_id=ctx.deps.user_id, path=path, offset=offset, limit=limit
            )
    except (errors.NotFoundError, errors.RequestError) as exc:
        raise ModelRetry(exc.msg) from exc


async def search_conversation_history(ctx: RunContext[ChatAgentDeps], query: str) -> str:
    """
    按关键字检索当前对话中已被压缩或过早的历史消息

    :param ctx: 运行上下文
    :param query: 检索关键字
    :return:
    """
    if not ctx.deps.conversation_id:
        return '当前没有可检索的对话'
    try:
        async with async_db_session() as db:
            result = await ai_buddy_message_history_service.search(
                db=db, conversation_id=ctx.deps.conversation_id, user_id=ctx.deps.user_id, q=query, cursor=None, limit=8
            )
    except errors.RequestError as exc:
        raise ModelRetry(exc.msg) from exc
    if not result.items:
        return '未找到匹配的历史消息'
    lines = [f'- #{item.message_index} {item.role}：{item.excerpt}' for item in result.items]
    suffix = '\n仍有更多匹配，请使用更具体的关键字' if result.has_more else ''
    return '匹配的历史消息：\n' + '\n'.join(lines) + suffix


async def list_artifacts(ctx: RunContext[ChatAgentDeps]) -> str:
    """
    列出当前用户已保存的工作产物

    :param ctx: 运行上下文
    :return:
    """
    async with async_db_session() as db:
        rows = await ai_buddy_artifact_service.get_all(db=db, user_id=ctx.deps.user_id)
    if not rows:
        return '没有可用产物'
    lines = [f'- #{item.id} {item.title}（{item.kind}）' for item in rows]
    return '产物列表：\n' + '\n'.join(lines)


async def get_artifact(ctx: RunContext[ChatAgentDeps], artifact_id: int) -> str:
    """
    读取一条工作产物的完整内容

    :param ctx: 运行上下文
    :param artifact_id: 产物 ID
    :return:
    """
    try:
        async with async_db_session() as db:
            artifact = await ai_buddy_artifact_service.get(db=db, pk=artifact_id, user_id=ctx.deps.user_id)
    except errors.NotFoundError:
        return '产物不存在'
    content = artifact.content
    if len(content) > _ARTIFACT_CONTENT_CHARS:
        content = f'{content[:_ARTIFACT_CONTENT_CHARS]}\n…内容已截断'
    return f'## 产物：{artifact.title}（{artifact.kind}）\n\n{content}'


async def write_artifact(
    ctx: RunContext[ChatAgentDeps],
    title: str,
    kind: AIBuddyArtifactKind,
    content: str,
    artifact_id: int | None = None,
) -> str:
    """
    将工作结果写入产物；传入 artifact_id 时更新已有产物

    :param ctx: 运行上下文
    :param title: 标题
    :param kind: 产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他
    :param content: 文本内容
    :param artifact_id: 产物 ID
    :return:
    """
    title_text = title.strip()
    content_text = content.strip()
    if not title_text or not content_text:
        return '标题和内容都不能为空'
    async with async_db_session.begin() as db:
        if artifact_id is not None:
            try:
                await ai_buddy_artifact_service.update(
                    db=db,
                    pk=artifact_id,
                    user_id=ctx.deps.user_id,
                    obj=UpdateAIBuddyArtifactParam(title=title_text, kind=kind, content=content_text),
                )
            except errors.NotFoundError:
                return '产物不存在'
            return f'已更新产物 #{artifact_id}'
        created = await ai_buddy_artifact_service.create(
            db=db,
            user_id=ctx.deps.user_id,
            obj=CreateAIBuddyArtifactParam(title=title_text, kind=kind, content=content_text),
        )
        return f'已创建产物 #{created.id}'
