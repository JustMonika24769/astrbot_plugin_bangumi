from typing import Literal

RenderMode = Literal["pillow", "playwright", "rpc"]
DEFAULT_RENDER_MODE: RenderMode = "pillow"


def normalize_render_mode(value: object) -> RenderMode:
    if not isinstance(value, str):
        return DEFAULT_RENDER_MODE

    normalized = value.strip().lower()
    if normalized == "html":
        return "playwright"
    if normalized == "pillow":
        return "pillow"
    if normalized == "playwright":
        return "playwright"
    if normalized == "rpc":
        return "rpc"
    return DEFAULT_RENDER_MODE
