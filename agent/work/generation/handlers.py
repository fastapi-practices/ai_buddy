from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.work.generation.base import GenerationHandler
from backend.plugin.ai_buddy.agent.work.generation.image import ImageGenerationHandler
from backend.plugin.ai_buddy.agent.work.generation.text import TextGenerationHandler
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType

_GENERATION_HANDLERS: dict[AIBuddyChatGenerationType, GenerationHandler] = {
    AIBuddyChatGenerationType.text: TextGenerationHandler(),
    AIBuddyChatGenerationType.image: ImageGenerationHandler(),
}


def get_generation_handler(generation_type: AIBuddyChatGenerationType) -> GenerationHandler:
    """
    获取生成模式处理器

    :param generation_type: 生成模式
    :return:
    """
    handler = _GENERATION_HANDLERS.get(generation_type)
    if handler is None:
        raise errors.RequestError(msg='暂不支持的生成模式')
    return handler
