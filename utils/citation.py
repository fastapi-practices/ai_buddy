from collections.abc import Sequence
from urllib.parse import urlsplit

from pydantic_ai.messages import TextPart, WebCitationSource

from backend.plugin.ai_buddy.schema.citation import AIBuddyCitationDetail


def text_part_citations(parts: Sequence[TextPart]) -> list[AIBuddyCitationDetail]:
    """
    保留供应商明确返回的网页引用，不从模型正文推测来源

    :param parts: 模型文本片段
    :return:
    """
    web_sources = (
        source
        for part in parts
        for citation in (part.citations or [])[:100]
        for source in citation.sources
        if isinstance(source, WebCitationSource)
    )
    sources: dict[str, AIBuddyCitationDetail] = {}
    for source in web_sources:
        if len(source.url) > 4096:
            continue
        try:
            parsed = urlsplit(source.url)
            if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        sources[source.url] = AIBuddyCitationDetail(
            url=source.url, title=source.title[:512] if source.title else parsed.hostname
        )
        if len(sources) == 100:
            break
    return list(sources.values())
