"""Unit tests for the torrent-mode dispatcher (webseed + active_seed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from grabarr.core.enums import TorrentMode
from grabarr.torrents.active_seed import shutdown_active_seed_server
from grabarr.torrents.bencode import decode
from grabarr.torrents.server import generate_torrent


@pytest.fixture
def seed_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.epub"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 4096)
    return path


def test_webseed_mode_emits_bep19_url_list(tmp_path: Path, seed_file: Path) -> None:
    result = generate_torrent(
        mode=TorrentMode.WEBSEED,
        file_path=seed_file,
        announce_url="http://tracker.local/announce",
        webseed_url="http://grabarr.local/seed/abc",
        display_name="Sample.epub",
    )
    assert result.mode == TorrentMode.WEBSEED
    assert len(result.info_hash) == 40
    assert result.piece_count >= 1

    t = decode(result.bencoded)
    assert t[b"announce"] == b"http://tracker.local/announce"
    # webseed.py emits url-list as a bare string (not a 1-element list) for
    # qBittorrent/Transmission compatibility — see the WHY comment in
    # grabarr/torrents/webseed.py.
    assert t[b"url-list"] == b"http://grabarr.local/seed/abc"
    assert t[b"httpseeds"] == [b"http://grabarr.local/seed/abc"]
    info = t[b"info"]
    assert info[b"length"] == seed_file.stat().st_size
    assert info[b"name"] == b"Sample.epub"


def test_active_seed_mode_registers_torrent(tmp_path: Path, seed_file: Path, monkeypatch) -> None:
    # Isolate the libtorrent session to tmp_path so we don't pollute data/.
    from grabarr.core import config as config_module
    from grabarr.torrents import active_seed

    monkeypatch.setenv("GRABARR_SERVER__DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    config_module._settings_singleton = None
    active_seed._server = None

    try:
        result = generate_torrent(
            mode=TorrentMode.ACTIVE_SEED,
            file_path=seed_file,
            announce_url="http://tracker.local/announce",
            webseed_url="http://grabarr.local/seed/abc",  # ignored in this mode
            display_name="Sample.epub",
        )
        assert result.mode == TorrentMode.ACTIVE_SEED
        assert len(result.info_hash) == 40

        t = decode(result.bencoded)
        # Active-seed torrents do NOT carry a url-list (that's BEP-19-only).
        assert b"url-list" not in t
        assert t[b"announce"] == b"http://tracker.local/announce"
        info = t[b"info"]
        assert info[b"length"] == seed_file.stat().st_size

        server = active_seed.get_active_seed_server()
        assert server.active_count() == 1
    finally:
        shutdown_active_seed_server()
        # Reset the singleton for any subsequent test.
        active_seed._server = None
