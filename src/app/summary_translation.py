import re
from typing import TYPE_CHECKING

from astrbot.api import logger

if TYPE_CHECKING:
    from astrbot.api.star import Context


TRANSLATE_TO_CHINESE_SYSTEM_PROMPT = "Translate to chinese (output translation only):"
_JAPANESE_KANA_PATTERN = re.compile(r"[\u3040-\u30ff\uff66-\uff9f]")


def summary_needs_chinese_translation(text: str) -> bool:
    """Return True for Japanese or mixed CN/JP summaries that contain kana."""
    return bool(_JAPANESE_KANA_PATTERN.search(text.strip()))


async def translate_text_to_chinese(
    context: "Context | None",
    text: str,
    *,
    feature_name: str,
) -> str:
    normalized_text = text.strip()
    if not normalized_text:
        return text

    if context is None:
        logger.warning(f"{feature_name}已开启,但 AstrBot Context 不可用,保留原文")
        return text

    try:
        provider = context.get_using_provider()
        if provider is None:
            logger.warning(f"{feature_name}已开启,但默认 chat provider 不可用,保留原文")
            return text

        provider_meta = provider.meta()
        provider_id = getattr(provider_meta, "id", None)
        if not isinstance(provider_id, str) or not provider_id:
            logger.warning(
                f"{feature_name}已开启,但默认 chat provider id 不可用,保留原文"
            )
            return text

        response = await context.llm_generate(
            chat_provider_id=provider_id,
            prompt=normalized_text,
            system_prompt=TRANSLATE_TO_CHINESE_SYSTEM_PROMPT,
        )
    except Exception as e:
        logger.error(f"{feature_name}失败,保留原文: {e}")
        return text

    translated_text = getattr(response, "completion_text", "").strip()
    if not translated_text:
        logger.warning(f"{feature_name}返回空文本,保留原文")
        return text
    return translated_text
