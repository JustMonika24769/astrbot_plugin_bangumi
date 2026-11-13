from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from astrbot.api import logger

_CACHE_HEADER = b"BANGUMI-COVER/1"
_MAX_CACHE_BYTES = 20 * 1024 * 1024


def image_mime(image: bytes) -> str | None:
    """Identify supported raster images without trusting HTTP Content-Type."""
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        return "image/webp"
    if image[4:8] == b"ftyp" and image[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


class CoverDiskCache:
    """Keep covers until explicitly removed; checksum and atomically replace files."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    async def read(self, subject_id: int) -> tuple[bytes, str] | None:
        return await asyncio.to_thread(self._read, subject_id)

    def _read(self, subject_id: int) -> tuple[bytes, str] | None:
        path = self.directory / f"{subject_id}.cover"
        try:
            with path.open("rb") as file:
                payload = file.read(_MAX_CACHE_BYTES + 1)
            if len(payload) > _MAX_CACHE_BYTES:
                raise ValueError("cache file is too large")
            header, checksum, image = payload.split(b"\n", 2)
            mime = image_mime(image)
            if (
                header != _CACHE_HEADER
                or checksum != hashlib.sha256(image).hexdigest().encode("ascii")
                or mime is None
            ):
                raise ValueError("cache checksum or image signature does not match")
            return image, mime
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning(f"Cannot read cached Bangumi cover {subject_id}: {exc}")
            return None

    async def write(self, subject_id: int, image: bytes) -> None:
        await asyncio.to_thread(self._write, subject_id, image)

    def _write(self, subject_id: int, image: bytes) -> None:
        if image_mime(image) is None or len(image) + 100 > _MAX_CACHE_BYTES:
            return
        temporary: Path | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.directory,
                prefix=f".{subject_id}-",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary = Path(file.name)
                checksum = hashlib.sha256(image).hexdigest().encode("ascii")
                file.write(_CACHE_HEADER + b"\n" + checksum + b"\n" + image)
            os.replace(temporary, self.directory / f"{subject_id}.cover")
        except OSError as exc:
            logger.warning(f"Cannot save cached Bangumi cover {subject_id}: {exc}")
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
