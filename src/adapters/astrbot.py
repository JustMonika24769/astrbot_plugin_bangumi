import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.star import StarTools

from ..app import AppImages, AppResponse, AppText


class AstrBotResponseMapper:
    """把应用层响应转换为 AstrBot 命令结果。"""

    def to_event_result(self, event: AstrMessageEvent, response: AppResponse) -> object:
        if isinstance(response, AppText):
            return event.plain_result(response.text)
        if isinstance(response, AppImages):
            images = [
                Comp.Image.fromBase64(base64_image)
                for base64_image in response.base64_images
            ]
            return event.chain_result(images)
        raise TypeError(f"Unsupported app response: {type(response)!r}")


class StarToolsGroupNotifier:
    """把订阅通知端口适配到 AstrBot 的群消息发送 API。"""

    async def send_episode_update(
        self, group_id: str, image_base64: str | None, fallback_text: str
    ) -> None:
        message_chain = MessageChain()
        if image_base64:
            message_chain.base64_image(image_base64)
        else:
            message_chain.message(fallback_text)
        await StarTools.send_message_by_id(
            type="GroupMessage",
            id=group_id,
            message_chain=message_chain,
        )
