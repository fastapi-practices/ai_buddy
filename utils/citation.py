from collections.abc import Sequence
from urllib.parse import urlsplit

from pydantic_ai.messages import TextPart

from backend.plugin.ai_buddy.schema.citation import AIBuddyCitationDetail


def text_part_citations(parts: Sequence[TextPart]) -> list[AIBuddyCitationDetail]:
    """
    保留供应商明确返回的网页引用，不从模型正文推测来源

    :param parts: 模型文本片段
    :return:
    """
    sources: dict[str, AIBuddyCitationDetail] = {}
    for part in parts:
        annotations = (part.provider_details or {}).get('annotations')
        if not isinstance(annotations, list):
            continue
        for annotation in annotations[:100]:
            if not isinstance(annotation, dict) or annotation.get('type') != 'url_citation':
                continue
            citation = annotation.get('url_citation', annotation)
            if not isinstance(citation, dict):
                continue
            url = citation.get('url')
            if not isinstance(url, str) or len(url) > 4096:
                continue
            try:
                parsed = urlsplit(url)
                if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
                    continue
            except ValueError:
                continue
            title = citation.get('title')
            sources[url] = AIBuddyCitationDetail(
                url=url, title=title[:512] if isinstance(title, str) else parsed.hostname
            )
            if len(sources) == 100:
                return list(sources.values())
    return list(sources.values())
