from backend.common.exception import errors

CRON_PROMPT_MAX_LEN = 2000
CRON_NAME_MAX_LEN = 80


def require_cron_prompt(prompt: str) -> str:
    """
    校验提示词非空且不超过上限

    :param prompt: 提示词
    :return:
    """
    text = prompt.strip()
    if not text:
        raise errors.RequestError(msg='提示词不能为空')
    if len(text) > CRON_PROMPT_MAX_LEN:
        raise errors.RequestError(msg=f'提示词最多 {CRON_PROMPT_MAX_LEN} 个字符')
    return text


def require_cron_name(name: str | None, *, prompt: str, fallback: str) -> str:
    """
    返回非空展示名称，空白则回落到提示词首行

    :param name: 用户填写的名称
    :param prompt: 提示词
    :param fallback: 名称与提示词都空时的回落
    :return:
    """
    text = (name or '').strip()
    if not text:
        text = next((' '.join(line.split())[:40] for line in prompt.splitlines() if line.strip()), fallback)
    if len(text) > CRON_NAME_MAX_LEN:
        raise errors.RequestError(msg=f'任务名称最多 {CRON_NAME_MAX_LEN} 个字符')
    return text
