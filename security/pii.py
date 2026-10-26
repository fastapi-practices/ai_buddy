import re

from collections.abc import Callable

from pydantic_ai_harness.guardrails import GuardrailResult

_PHONE = re.compile(r'(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}(?!\d)')
_ID_CARD = re.compile(r'(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)')
_EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
_BANK_CARD = re.compile(r'(?<!\d)(?:\d[ -]*?){13,19}(?!\d)')


def _mask_keep_tail(value: str, *, keep: int = 4) -> str:
    compact = re.sub(r'[\s-]+', '', value)
    if len(compact) <= keep:
        return '*' * len(compact)
    return '*' * (len(compact) - keep) + compact[-keep:]


def redact_pii(text: str) -> str:
    """
    脱敏证件号、手机号、邮箱和银行卡号，叠在密钥脱敏之上

    :param text: 原文
    :return:
    """
    if not text:
        return text
    redacted = _PHONE.sub(lambda match: _mask_keep_tail(match.group(0)), text)
    redacted = _ID_CARD.sub(lambda match: _mask_keep_tail(match.group(0)), redacted)
    redacted = _EMAIL.sub(_mask_email, redacted)
    return _BANK_CARD.sub(_mask_bank_card, redacted)


def _mask_bank_card(match: re.Match[str]) -> str:
    digits = re.sub(r'\D', '', match.group(0))
    if (
        not 13 <= len(digits) <= 19
        or sum(sum(divmod(int(char) * (2 if index % 2 else 1), 10)) for index, char in enumerate(reversed(digits))) % 10
    ):
        return match.group(0)
    return _mask_keep_tail(digits)


def _mask_email(match: re.Match[str]) -> str:
    name, _, domain = match.group(0).partition('@')
    if not name:
        return '***@' + domain
    return name[0] + '***@' + domain


def compose_text_guard(*guards: Callable[[str], str | GuardrailResult]) -> Callable[[str], GuardrailResult]:
    """
    串联文本脱敏函数，兼容返回原文或 GuardrailResult 的检测器

    :param guards: 脱敏函数
    :return:
    """

    def _guard(text: str) -> GuardrailResult:
        current = text
        for item in guards:
            outcome = item(current)
            if isinstance(outcome, GuardrailResult):
                if outcome.action == 'allow':
                    continue
                if outcome.action != 'replace' or not isinstance(outcome.replacement, str):
                    return outcome
                current = outcome.replacement
                continue
            current = outcome
        if current != text:
            return GuardrailResult.replace(current)
        return GuardrailResult.allow()

    return _guard
