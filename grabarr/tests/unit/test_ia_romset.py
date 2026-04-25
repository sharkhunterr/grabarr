"""Unit tests for the Internet Archive ROM romset filename-matching path.

When an IA item lists many files of the preferred format (no-intro /
redump romsets contain thousands of ZIPs each), the format-only ladder
picks an arbitrary file. The romset path scores filenames against
the user's query and picks the best overlap.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from grabarr.adapters.internet_archive import (
    InternetArchiveAdapter,
    _filename_match_score,
    _tokenise,
)
from grabarr.core.enums import MediaType


def test_ia_tokenise() -> None:
    assert _tokenise("Super Mario World (USA).zip") == {
        "super", "mario", "world", "usa", "zip",
    }
    assert _tokenise("") == set()


def test_ia_filename_match_picks_query_match_over_alphabetical() -> None:
    query_tokens = _tokenise("super mario world")
    cands = [
        "Adventure Island (USA).zip",
        "Super Mario World (USA).zip",
        "Zelda - Link to the Past.zip",
    ]
    scored = sorted(cands, key=lambda n: _filename_match_score(n, query_tokens), reverse=True)
    assert scored[0] == "Super Mario World (USA).zip"


@pytest.mark.asyncio
async def test_ia_get_download_info_uses_query_hint_for_romsets() -> None:
    """For a multi-file ROM romset, query_hint disambiguates the file."""
    metadata = {
        "server": "ia800800.us.archive.org",
        "dir": "/items/nointro.snes",
        "files": [
            {"name": "Adventure Island (USA).zip", "format": "ZIP", "size": "100000"},
            {"name": "Super Mario World (USA).zip", "format": "ZIP", "size": "350000"},
            {"name": "Yoshi's Island (USA).zip", "format": "ZIP", "size": "1500000"},
            {"name": "Zelda - Link to the Past.zip", "format": "ZIP", "size": "1100000"},
            {"name": "Castlevania (USA).zip", "format": "ZIP", "size": "200000"},
        ],
    }
    adapter = InternetArchiveAdapter()
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://archive.org/metadata/nointro.snes").mock(
            return_value=httpx.Response(200, json=metadata)
        )
        info = await adapter.get_download_info(
            "nointro.snes", MediaType.GAME_ROM, query_hint="Super Mario World"
        )
    assert info.filename_hint == "Super Mario World (USA).zip"
    assert info.download_url.endswith("/Super Mario World (USA).zip")


@pytest.mark.asyncio
async def test_ia_get_download_info_skips_match_below_threshold() -> None:
    """With ≤ 3 candidates, the format-score winner is authoritative."""
    metadata = {
        "server": "ia800800.us.archive.org",
        "dir": "/items/single_rom_item",
        "files": [
            {"name": "Some ROM.zip", "format": "ZIP", "size": "10000"},
            {"name": "manifest.txt", "format": "Metadata", "size": "100"},
        ],
    }
    adapter = InternetArchiveAdapter()
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://archive.org/metadata/single_rom_item").mock(
            return_value=httpx.Response(200, json=metadata)
        )
        info = await adapter.get_download_info(
            "single_rom_item", MediaType.GAME_ROM, query_hint="ZeldaQueryThatDoesntMatch"
        )
    assert info.filename_hint == "Some ROM.zip"


@pytest.mark.asyncio
async def test_ia_get_download_info_no_query_hint_falls_back_to_format() -> None:
    """No query_hint → first top-tier file (legacy v1.0 behaviour)."""
    metadata = {
        "server": "ia800800.us.archive.org",
        "dir": "/items/big_pack",
        "files": [
            {"name": f"Game{i:02d}.zip", "format": "ZIP", "size": "1000"} for i in range(10)
        ],
    }
    adapter = InternetArchiveAdapter()
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://archive.org/metadata/big_pack").mock(
            return_value=httpx.Response(200, json=metadata)
        )
        info = await adapter.get_download_info("big_pack", MediaType.GAME_ROM)
    assert info.filename_hint.endswith(".zip")


# --------------------------------------------------------------------------
# IA login + access-restricted filter
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ia_search_drops_access_restricted_filter_when_logged_in() -> None:
    """With credentials configured, search must NOT filter out CDL items."""
    adapter = InternetArchiveAdapter(login_email="x@y", login_password="pw")
    captured_q: list[str] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured_q.append(request.url.params.get("q") or "")
        return httpx.Response(200, json={"response": {"docs": []}})

    with respx.mock(assert_all_called=False) as mock:
        # Stub the login endpoint so _ensure_logged_in succeeds.
        mock.post("https://archive.org/services/xauthn/").mock(
            return_value=httpx.Response(
                200, headers={"set-cookie": "logged-in-user=x; Path=/"}
            )
        )
        mock.get("https://archive.org/advancedsearch.php").mock(side_effect=_capture)
        from grabarr.core.models import SearchFilters

        await adapter.search("mario", MediaType.GAME_ROM, SearchFilters(), limit=5)
    assert captured_q, "search should have hit advancedsearch.php"
    assert "-access-restricted-item:true" not in captured_q[0]


@pytest.mark.asyncio
async def test_ia_search_keeps_access_restricted_filter_when_anonymous() -> None:
    """Without credentials, the v1.0 access-restricted filter still applies."""
    adapter = InternetArchiveAdapter()  # no login
    captured_q: list[str] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured_q.append(request.url.params.get("q") or "")
        return httpx.Response(200, json={"response": {"docs": []}})

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://archive.org/advancedsearch.php").mock(side_effect=_capture)
        from grabarr.core.models import SearchFilters

        await adapter.search("mario", MediaType.GAME_ROM, SearchFilters(), limit=5)
    assert captured_q
    assert "-access-restricted-item:true" in captured_q[0]


@pytest.mark.asyncio
async def test_ia_login_caches_cookies_on_first_call() -> None:
    """_ensure_logged_in is single-flight + cached for subsequent calls."""
    adapter = InternetArchiveAdapter(login_email="x@y", login_password="pw")
    login_count = 0

    def _login(_request: httpx.Request) -> httpx.Response:
        nonlocal login_count
        login_count += 1
        return httpx.Response(
            200, headers={"set-cookie": "logged-in-user=x; Path=/"}
        )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://archive.org/services/xauthn/").mock(side_effect=_login)
        await adapter._ensure_logged_in()
        await adapter._ensure_logged_in()
        await adapter._ensure_logged_in()
    assert login_count == 1
    assert adapter._auth_cookies and "logged-in-user" in adapter._auth_cookies


def test_ia_drop_auth_on_401_clears_cache() -> None:
    adapter = InternetArchiveAdapter(login_email="x@y", login_password="pw")
    adapter._auth_cookies = {"logged-in-user": "x"}
    adapter._drop_auth_on_401(401)
    assert adapter._auth_cookies is None


def test_ia_drop_auth_ignores_non_401() -> None:
    adapter = InternetArchiveAdapter(login_email="x@y", login_password="pw")
    adapter._auth_cookies = {"logged-in-user": "x"}
    adapter._drop_auth_on_401(500)
    assert adapter._auth_cookies == {"logged-in-user": "x"}
