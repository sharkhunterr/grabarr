"""Unit tests for the ROM source adapters added in feature 002.

Covers:
  - Vimm's Lair search HTML parser + media[]-array download resolution
  - Edge Emulation POST search + direct /download URL extraction

The Internet Archive romset enhancement is tested separately in
``test_ia_romset.py``.
"""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from grabarr.adapters.edge_emulation import (
    EdgeEmulationAdapter,
    _parse_edge_results,
    _parse_size_edge,
)
from grabarr.adapters.vimm import (
    VimmsLairAdapter,
    _decode_b64_filename,
    _extract_media_array,
    _parse_vimm_list,
)
from grabarr.core.enums import MediaType
from grabarr.core.models import SearchFilters

# --------------------------------------------------------------------------
# Vimm
# --------------------------------------------------------------------------


_VIMM_LIST_HTML = (
    '<html><body><table>'
    '<tr style="font-size:10pt"><td>Title</td><td>Region</td></tr>'
    '<tr><td><a href="/vault/287">Dr. Mario</a></td>'
    '<td><img class="flag" title="USA"><img class="flag" title="Japan"></td>'
    '<td>1.1</td><td>en</td></tr>'
    '<tr><td><a href="/vault/535">Mario Bros.</a></td>'
    '<td><img class="flag" title="World"></td>'
    '<td>1.0</td><td>-</td></tr>'
    '<tr><td><a href="/vault/94591">Super Mario Bros. (Pirate)</a></td>'
    '<td><img class="flag" title="Asia"></td>'
    '<td>1.0</td><td>en</td></tr>'
    '</table></body></html>'
)


def test_vimm_parses_list_table() -> None:
    rows = _parse_vimm_list(_VIMM_LIST_HTML, "NES", "mario", "vimm", limit=10)
    assert [r.external_id for r in rows] == ["287", "535", "94591"]
    # Title is the bare game name; torznab adds [Console][Region] tags.
    assert rows[0].title == "Dr. Mario"
    assert rows[0].metadata.get("console_label") == "NES"
    assert rows[0].metadata.get("region_label") == "USA"
    # USA region → en, format is the per-system extension.
    assert rows[0].language == "en"
    assert rows[0].format == "nes"
    # Pirate rows are score-penalised.
    assert rows[2].quality_score < rows[1].quality_score
    assert rows[2].metadata.get("version_label") == "Pirate"
    # _TYPICAL_SIZE placeholder so Prowlarr doesn't render 0 B.
    assert rows[0].size_bytes and rows[0].size_bytes > 0
    assert rows[0].metadata.get("size_is_estimate") is True


def test_vimm_parses_list_respects_limit() -> None:
    rows = _parse_vimm_list(_VIMM_LIST_HTML, "NES", "mario", "vimm", limit=2)
    assert len(rows) == 2


def test_vimm_extract_media_array() -> None:
    html = """
    <html><script>
    let media=[{"ID":71335,"GoodTitle":"RHIuIE1hcmlvLm5lcw==","SortOrder":1,"Zipped":"28"},
               {"ID":275,"GoodTitle":"RHIuIE1hcmlvIChSZXYgMSkubmVz","SortOrder":1,"Zipped":"28"}];
    document.addEventListener('DOMContentLoaded',function(){});
    </script></html>
    """
    media = _extract_media_array(html)
    assert len(media) == 2
    assert media[0]["ID"] == 71335
    assert _decode_b64_filename(media[0]["GoodTitle"]) == "Dr. Mario.nes"


def test_vimm_extract_media_handles_missing_array() -> None:
    assert _extract_media_array("<html>no array</html>") == []


@pytest.mark.asyncio
async def test_vimm_search_dispatches_per_system_and_merges() -> None:
    adapter = VimmsLairAdapter()
    nes_params = {"p": "list", "system": "NES", "q": "mario"}
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://vimm.net/vault/", params=nes_params).mock(
            return_value=httpx.Response(200, text=_VIMM_LIST_HTML)
        )
        # All other systems return empty results.
        mock.get("https://vimm.net/vault/").mock(
            return_value=httpx.Response(200, text="<html><body></body></html>")
        )
        # Pin the search to NES via system: hint to avoid a parallel storm.
        results = await adapter.search(
            "mario system:NES", MediaType.GAME_ROM, SearchFilters(), limit=10
        )
    assert results, "expected at least one Vimm hit"
    assert all(r.metadata.get("vimm_system") == "NES" for r in results)
    assert results[0].external_id == "287"


@pytest.mark.asyncio
async def test_vimm_get_download_info_resolves_media_id() -> None:
    adapter = VimmsLairAdapter()
    encoded = base64.b64encode(b"Dr. Mario.nes").decode()
    page = f"""
    <html><script>
    let media=[{{"ID":71335,"GoodTitle":"{encoded}","SortOrder":1,"Zipped":"28"}}];
    </script></html>
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://vimm.net/vault/287").mock(
            return_value=httpx.Response(200, text=page)
        )
        info = await adapter.get_download_info("287", MediaType.GAME_ROM)
    assert info.download_url == "https://dl3.vimm.net/?mediaId=71335"
    assert info.filename_hint == "Dr. Mario.nes"
    assert info.size_bytes == 28 * 1024
    assert info.extra_headers.get("Referer") == "https://vimm.net/vault/287"


# --------------------------------------------------------------------------
# Edge Emulation
# --------------------------------------------------------------------------


_EDGE_RESULTS = (
    '<html><body><div class="grid">'
    '<div class="item"><details data-name="Super Mario 64 (USA).zip">'
    '<summary>Super Mario 64 (USA)</summary>'
    '<p><a href="/download/nintendo-64/Super%20Mario%2064%20%28USA%29.zip">'
    'download</a> (<span>5.95m, 1431 DLs</span>)</p>'
    '<p>system: <span>Nintendo 64</span></p>'
    '<p>unpacked size: <span>8.00m</span></p>'
    '</details></div>'
    '<div class="item"><details data-name="Mario Kart 64 (USA).zip">'
    '<summary>Mario Kart 64 (USA)</summary>'
    '<p><a href="/download/nintendo-64/Mario%20Kart%2064%20%28USA%29.zip">'
    'download</a> (<span>8.57m, 641 DLs</span>)</p>'
    '<p>system: <span>Nintendo 64</span></p>'
    '</details></div>'
    '</div></body></html>'
)


def test_edge_parse_size() -> None:
    assert _parse_size_edge("5.95m") == int(5.95 * 1024 ** 2)
    assert _parse_size_edge("948.52k") == int(948.52 * 1024)
    assert _parse_size_edge("1.00g") == 1024 ** 3
    assert _parse_size_edge("") is None
    assert _parse_size_edge("garbage") is None


def test_edge_parse_results() -> None:
    results = _parse_edge_results(_EDGE_RESULTS, "mario", "edge_emulation", limit=10)
    assert len(results) == 2
    first = results[0]
    assert first.external_id == "nintendo-64/Super%20Mario%2064%20%28USA%29.zip"
    # Title is bare; torznab builds [Console][Region] from metadata.
    assert first.title.startswith("Super Mario 64")
    assert "(USA)" not in first.title  # the region paren stripped
    assert first.metadata["console_label"] == "N64"
    assert first.metadata["region_label"] == "USA"
    assert first.format == "zip"
    assert first.size_bytes == int(5.95 * 1024 ** 2)
    assert first.quality_score >= 50
    assert first.metadata["edge_filename"] == "Super Mario 64 (USA).zip"


@pytest.mark.asyncio
async def test_edge_search_posts_form() -> None:
    adapter = EdgeEmulationAdapter()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://edgeemu.net/search.php").mock(
            return_value=httpx.Response(200, text=_EDGE_RESULTS)
        )
        results = await adapter.search("mario", MediaType.GAME_ROM, SearchFilters(), limit=10)
    assert results
    # Confirm the POST body shape.
    request = route.calls[-1].request
    assert b"search=mario" in request.content
    assert b"system=all" in request.content


@pytest.mark.asyncio
async def test_edge_get_download_info_builds_url() -> None:
    adapter = EdgeEmulationAdapter()
    info = await adapter.get_download_info(
        "nintendo-64/Super%20Mario%2064%20%28USA%29.zip", MediaType.GAME_ROM
    )
    assert info.download_url == (
        "https://edgeemu.net/download/nintendo-64/Super%20Mario%2064%20%28USA%29.zip"
    )
    assert info.filename_hint == "Super Mario 64 (USA).zip"


@pytest.mark.asyncio
async def test_edge_search_pins_system_via_hint() -> None:
    adapter = EdgeEmulationAdapter()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://edgeemu.net/search.php").mock(
            return_value=httpx.Response(200, text=_EDGE_RESULTS)
        )
        await adapter.search(
            "mario system:nintendo-snes", MediaType.GAME_ROM, SearchFilters(), limit=5
        )
    body = route.calls[-1].request.content
    # The hint stripped from query, system pinned in the form body.
    assert b"system=nintendo-snes" in body
    assert b"search=mario" in body
    assert b"system:nintendo-snes" not in body  # hint not leaked into search field
