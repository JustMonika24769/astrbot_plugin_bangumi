from typing import Literal

RenderMode = Literal["html", "pillow"]


def normalize_render_mode(value: object) -> RenderMode:
    if isinstance(value, str) and value.strip().lower() == "pillow":
        return "pillow"
    return "html"
