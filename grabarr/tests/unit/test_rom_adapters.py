"""Unit tests for the ROM source adapters added in feature 002.

Covers:
  - Vimm's Lair search HTML parser + media[]-array download resolution

The Internet Archive romset enhancement is tested separately in
``test_ia_romset.py``.
"""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

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
    # Title gets the [<system>] tag suffix.
    assert rows[0].title == "Dr. Mario [NES]"
    # USA region → en, format is the per-system extension.
    assert rows[0].language == "en"
    assert rows[0].format == "nes"
    # Pirate rows are score-penalised.
    assert rows[2].quality_score < rows[1].quality_score


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
