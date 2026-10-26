import re

from typing import Any

_THINKING_RE = re.compile(
    r'<(?:think|thinking)>[\s\S]*?</(?:think|thinking)>\s*',
    re.IGNORECASE,
)
_THINKING_OPEN_RE = re.compile(r'<(?:think|thinking)>', re.IGNORECASE)
_THINKING_CLOSE_RE = re.compile(r'</(?:think|thinking)>', re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """
    去掉模型输出里的思考标签，只留可见正文

    :param text: 模型原文
    :return:
    """
    cleaned = _THINKING_RE.sub('', text)
    while True:
        close_match = _THINKING_CLOSE_RE.search(cleaned)
        if close_match is None:
            break
        open_match = _THINKING_OPEN_RE.search(cleaned)
        if open_match is not None and open_match.start() < close_match.start():
            break
        cleaned = cleaned[close_match.end() :]
    open_match = _THINKING_OPEN_RE.search(cleaned)
    if open_match is not None:
        cleaned = cleaned[: open_match.start()]
    return cleaned.strip()


def llm_output_text(result: Any) -> str:
    """
    从 Pydantic AI 一次调用结果抽出纯文本

    :param result: Agent.run 结果
    :return:
    """
    output = getattr(result, 'output', None)
    if isinstance(output, str):
        return _strip_thinking(output)
    return _strip_thinking(str(output or ''))
