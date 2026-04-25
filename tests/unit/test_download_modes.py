"""Unit tests for the download-mode dispatcher (sync / async / hybrid)."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response

from grabarr.core.enums import DownloadMode
from grabarr.core.models import DownloadInfo
from grabarr.downloads.manager import run_download


def _info(size_bytes: int | None, url: str = "https://src.example/file.epub") -> DownloadInfo:
    return DownloadInfo(
        download_url=url,
        size_bytes=size_bytes,
        content_type="application/epub+zip",
        filename_hint="file.epub",
        extra_headers={},
    )


_EPUB_BODY = b"PK\x03\x04" + b"\x00" * 2048


@pytest.mark.asyncio
async def test_sync_mode_downloads_and_verifies(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://src.example/file.epub").mock(
            return_value=Response(200, content=_EPUB_BODY, headers={"content-type": "application/epub+zip"})
        )
        path, size, ct, report = await run_download(
            mode=DownloadMode.SYNC,
            info=_info(len(_EPUB_BODY)),
            token="tok-sync-01",
            downloads_root=tmp_path,
            expected_format="epub",
        )
    assert path.exists()
    assert size == len(_EPUB_BODY)
    assert ct == "application/epub+zip"
    assert report.passed
    assert report.format_matched == "epub"


@pytest.mark.asyncio
async def test_async_streaming_mode_runs_via_task(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://src.example/file.epub").mock(
            return_value=Response(200, content=_EPUB_BODY, headers={"content-type": "application/epub+zip"})
        )
        path, size, _ct, report = await run_download(
            mode=DownloadMode.ASYNC_STREAMING,
            info=_info(len(_EPUB_BODY)),
            token="tok-async-01",
            downloads_root=tmp_path,
            expected_format="epub",
        )
    assert path.exists()
    assert size == len(_EPUB_BODY)
    assert report.passed


@pytest.mark.asyncio
async def test_hybrid_uses_sync_below_threshold(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://src.example/file.epub").mock(
            return_value=Response(200, content=_EPUB_BODY, headers={"content-type": "application/epub+zip"})
        )
        path, size, _ct, report = await run_download(
            mode=DownloadMode.HYBRID,
            info=_info(len(_EPUB_BODY)),
            token="tok-hyb-01",
            downloads_root=tmp_path,
            expected_format="epub",
            hybrid_threshold_bytes=1_000_000_000,  # 1 GB → everything is "small"
        )
    assert path.exists()
    assert report.passed


@pytest.mark.asyncio
async def test_hybrid_uses_async_above_threshold(tmp_path: Path) -> None:
    big_body = b"PK\x03\x04" + b"\x00" * (2 * 1024 * 1024)  # 2 MiB
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://src.example/file.epub").mock(
            return_value=Response(
                200,
                content=big_body,
                headers={"content-type": "application/epub+zip"},
            )
        )
        path, size, _ct, report = await run_download(
            mode=DownloadMode.HYBRID,
            info=_info(len(big_body)),
            token="tok-hyb-02",
            downloads_root=tmp_path,
            expected_format="epub",
            hybrid_threshold_bytes=1024,  # 1 KiB → everything is "big"
        )
    assert path.exists()
    assert size == len(big_body)
    assert report.passed
