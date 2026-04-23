"""US1 MVP smoke test (task T090).

Exercises the full end-to-end path:
  1. Boot the FastAPI app via TestClient (runs lifespan → migrations + seeds).
  2. Fetch Prowlarr config → gives a fresh API key.
  3. Hit /torznab/.../api?t=caps → verify XML shape.
  4. Hit /torznab/.../api?t=search with mocked Internet Archive responses.
  5. Grab /torznab/.../download/{token}.torrent → verify bencoded torrent is valid
     with correct BEP-19 webseed URL.

All external HTTP to archive.org is mocked via respx so the test is
deterministic and runs offline.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from grabarr.torrents.bencode import decode


_IA_SEARCH_RESPONSE = {
    "response": {
        "docs": [
            {
                "identifier": "test-item-001",
                "title": "Test Book",
                "creator": "Test Author",
                "year": "1920",
                "language": "eng",
                "item_size": "1024",
                "mediatype": "texts",
            }
        ],
        "numFound": 1,
    }
}

_IA_METADATA_RESPONSE = {
    "server": "ia801234.us.archive.org",
    "dir": "/2/items/test-item-001",
    "files": [
        {"name": "test-item-001.epub", "format": "EPUB", "size": "2048"},
        {"name": "test-item-001_meta.xml", "format": "Metadata", "size": "256"},
    ],
}

# Minimal EPUB: ZIP magic + enough body for verification to accept it.
# EPUB files are ZIPs; the verifier only checks the first 4 bytes `PK\x03\x04`.
_FAKE_EPUB = b"PK\x03\x04" + b"\x00" * 500


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Spin up the app in an isolated working directory with a fresh DB."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRABARR_SERVER__DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GRABARR_SERVER__DOWNLOADS_DIR", str(tmp_path / "downloads"))
    # Default these tests to webseed so the BEP-19 url-list assertions hold.
    # The active_seed path is covered by tests/unit/test_torrent_modes.py.
    monkeypatch.setenv("GRABARR_TORRENT_MODE", "webseed")
    (tmp_path / "data").mkdir()
    (tmp_path / "downloads" / "incoming").mkdir(parents=True)
    (tmp_path / "downloads" / "ready").mkdir(parents=True)

    # Reset cached state from any prior test (but keep the registry —
    # adapter classes are module-level and don't re-register on reload).
    from grabarr.core import config as config_module
    from grabarr.db import session as session_module
    from grabarr.profiles import service as profiles_service

    config_module._settings_singleton = None
    session_module.reset_engine()
    profiles_service._ADAPTER_INSTANCES.clear()

    # Ensure adapters are imported at least once (registry populated).
    import grabarr.adapters  # noqa: F401

    from grabarr.api.app import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client

    session_module.reset_engine()
    config_module._settings_singleton = None
    profiles_service._ADAPTER_INSTANCES.clear()


def _extract_api_key(payload: dict) -> str:
    return next(f for f in payload["fields"] if f["name"] == "apiKey")["value"]


def test_us1_full_flow(app_client: TestClient) -> None:
    # 1. Prowlarr config → fresh API key.
    r = app_client.get("/api/prowlarr-config?profile=ebooks_public_domain")
    assert r.status_code == 200
    api_key = _extract_api_key(r.json())
    assert len(api_key) > 20

    # 2. Caps: returns valid XML mentioning category 7020 (ebook).
    r = app_client.get("/torznab/ebooks_public_domain/api?t=caps")
    assert r.status_code == 200
    assert "<caps>" in r.text
    assert "7020" in r.text

    # 3. Search: mock IA, expect one <item> in the RSS.
    from grabarr.adapters import get_registered_adapters
    assert "internet_archive" in get_registered_adapters()

    with respx.mock(assert_all_called=False) as mock:
        ia_search = mock.route(
            url__regex=r"https://archive\.org/advancedsearch\.php.*"
        ).mock(return_value=Response(200, json=_IA_SEARCH_RESPONSE))
        r = app_client.get(
            f"/torznab/ebooks_public_domain/api?t=search&q=test&apikey={api_key}&limit=1"
        )
        ia_call_count = ia_search.call_count
    assert r.status_code == 200
    assert ia_call_count >= 1, f"IA search mock never called (count={ia_call_count})"
    assert r.text.count("<item>") >= 1, f"expected >=1 item, got:\n{r.text}"

    # 4. Extract the download URL path from the RSS and hit it.
    m = re.search(r'<enclosure url="([^"]+)"', r.text)
    assert m is not None
    dl_url = m.group(1).replace("&amp;", "&")
    dl_path = urlparse(dl_url).path

    # 5. Hit /download/{token}.torrent. Mock IA metadata + file fetch.
    with respx.mock(assert_all_called=False) as mock:
        mock.route(url__regex=r"https://archive\.org/metadata/test-item-001.*").mock(
            return_value=Response(200, json=_IA_METADATA_RESPONSE)
        )
        mock.route(url__regex=r"https://ia801234\.us\.archive\.org/.*\.epub.*").mock(
            return_value=Response(
                200,
                content=_FAKE_EPUB,
                headers={"content-type": "application/epub+zip"},
            )
        )
        r = app_client.get(dl_path)

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/x-bittorrent"
    info_hash = r.headers.get("X-Grabarr-Info-Hash")
    assert info_hash and len(info_hash) == 40

    # 6. Decode the torrent and sanity-check its structure.
    torrent = decode(r.content)
    assert b"announce" in torrent
    assert b"url-list" in torrent  # BEP-19 webseed
    assert b"info" in torrent
    info = torrent[b"info"]
    assert info[b"length"] == len(_FAKE_EPUB)
    assert info[b"name"].endswith(b".epub")
    # The webseed URL must point back at our own server.
    webseeds = torrent[b"url-list"]
    assert any(b"/torznab/ebooks_public_domain/seed/" in w for w in webseeds)


def test_us1_caps_all_defaults(app_client: TestClient) -> None:
    """Every seeded default profile returns valid caps XML."""
    slugs = [
        "ebooks_general",
        "audiobooks_general",
        "ebooks_public_domain",
        "roms_all",
        "papers_academic",
        "music_general",
        "comics_general",
    ]
    for slug in slugs:
        r = app_client.get(f"/torznab/{slug}/api?t=caps")
        assert r.status_code == 200, f"{slug}: {r.status_code}"
        assert "<caps>" in r.text, f"{slug}: caps not found"
        assert "<categories>" in r.text


def test_us1_auth_wrong_key_returns_401(app_client: TestClient) -> None:
    r = app_client.get(
        "/torznab/ebooks_general/api?t=search&q=test&apikey=WRONG_KEY"
    )
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_us1_prowlarr_config_shape(app_client: TestClient) -> None:
    r = app_client.get("/api/prowlarr-config?profile=ebooks_general")
    assert r.status_code == 200
    blob = r.json()
    # Required Prowlarr Generic Torznab fields.
    assert blob["implementation"] == "Torznab"
    assert blob["protocol"] == "torrent"
    field_names = {f["name"] for f in blob["fields"]}
    assert {"baseUrl", "apiPath", "apiKey", "categories"} <= field_names
