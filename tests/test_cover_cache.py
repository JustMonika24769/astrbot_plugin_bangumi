from __future__ import annotations

import base64

import pytest

from astrbot_plugin_bangumi.src import cover_cache as module
from astrbot_plugin_bangumi.src.cover_cache import CoverDiskCache

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="
)


@pytest.mark.asyncio
async def test_missing_disk_cache_does_not_create_directories(tmp_path) -> None:
    directory = tmp_path / "covers"
    assert await CoverDiskCache(directory).read(1) is None
    assert not directory.exists()


@pytest.mark.asyncio
async def test_disk_cover_roundtrip_uses_signature_and_checksum(tmp_path) -> None:
    await CoverDiskCache(tmp_path).write(123, PNG)
    assert await CoverDiskCache(tmp_path).read(123) == (PNG, "image/png")
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.asyncio
async def test_disk_cover_checksum_detects_damage_after_valid_image_header(
    tmp_path,
) -> None:
    cache = CoverDiskCache(tmp_path)
    await cache.write(1, PNG)
    file = tmp_path / "1.cover"
    content = bytearray(file.read_bytes())
    content[-10] ^= 1
    file.write_bytes(content)
    assert await cache.read(1) is None


@pytest.mark.asyncio
async def test_error_page_is_not_written_to_disk(tmp_path) -> None:
    cache = CoverDiskCache(tmp_path)
    await cache.write(1, b"<html>upstream error</html>")
    assert not (tmp_path / "1.cover").exists()


@pytest.mark.asyncio
async def test_failed_atomic_replace_preserves_previous_cover(
    tmp_path, monkeypatch
) -> None:
    cache = CoverDiskCache(tmp_path)
    await cache.write(1, PNG)

    def fail_replace(*args):
        raise OSError("disk error")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    await cache.write(1, b"GIF89a" + b"changed image")
    assert await cache.read(1) == (PNG, "image/png")
    assert list(tmp_path.glob("*.tmp")) == []
