from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class AppText:
    text: str


@dataclass(frozen=True, slots=True)
class AppImages:
    base64_images: tuple[str, ...]

    @classmethod
    def single(cls, base64_image: str) -> AppImages:
        return cls(base64_images=(base64_image,))

    @classmethod
    def from_iterable(cls, base64_images: Iterable[str]) -> AppImages:
        return cls(base64_images=tuple(base64_images))


AppResponse: TypeAlias = AppText | AppImages


__all__ = ["AppImages", "AppResponse", "AppText"]
