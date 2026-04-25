"""The seven default profiles seeded on first launch (spec FR-012).

Each entry is a plain dict that maps directly onto the ``profiles`` row
shape. ``api_key_hash`` is populated by the seeder at insert time with a
freshly minted plaintext key; the operator reveals it via the Settings UI
or the Prowlarr-export endpoint.
"""

from __future__ import annotations

from typing import Any

from grabarr.core.enums import MediaType, ProfileMode


def _filters(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "languages": [],
        "preferred_formats": [],
        "min_year": None,
        "max_year": None,
        "min_size_mb": None,
        "max_size_mb": None,
        "require_isbn": False,
        "extra_query_terms": "",
    }
    base.update(overrides)
    return base


def _src(
    source_id: str,
    weight: float,
    *,
    timeout: int = 60,
    skip_if_member_required: bool = False,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "weight": weight,
        "timeout_seconds": timeout,
        "enabled": True,
        "skip_if_member_required": skip_if_member_required,
    }


DEFAULT_PROFILES: list[dict[str, Any]] = [
    {
        "slug": "ebooks_general",
        "name": "Ebooks General",
        "description": "General-purpose ebook search across AA, LibGen, IA, and Z-Library.",
        "media_type": MediaType.EBOOK.value,
        "sources": [
            _src("anna_archive", 1.2),
            _src("libgen", 1.0),
            _src("internet_archive", 0.9),
            _src("zlibrary", 0.7, skip_if_member_required=True),
        ],
        "filters": _filters(preferred_formats=["epub", "mobi", "pdf"]),
        "mode": ProfileMode.FIRST_MATCH.value,
        "newznab_categories": [7020],
    },
    {
        "slug": "audiobooks_general",
        "name": "Audiobooks General",
        "description": "Audiobooks via AA slow cascade and Internet Archive's LibriVox.",
        "media_type": MediaType.AUDIOBOOK.value,
        "sources": [
            _src("anna_archive", 1.2, timeout=120),
            _src("internet_archive", 0.9),
        ],
        "filters": _filters(preferred_formats=["mp3", "m4b"]),
        "mode": ProfileMode.FIRST_MATCH.value,
        "newznab_categories": [3030],
    },
    {
        "slug": "ebooks_public_domain",
        "name": "Ebooks — Public Domain",
        "description": "Public-domain-first: Internet Archive + LibGen, capped at 1929.",
        "media_type": MediaType.EBOOK.value,
        "sources": [
            _src("internet_archive", 1.5),
            _src("libgen", 0.9),
        ],
        "filters": _filters(max_year=1929),
        "mode": ProfileMode.FIRST_MATCH.value,
        "newznab_categories": [7020],
    },
    {
        "slug": "roms_all",
        "name": "ROMs — All Sources",
        "description": (
            "Aggregates every ROM-capable adapter: Vimm's Lair, Edge "
            "Emulation, RomsFun, CDRomance, MyAbandonware (PC abandonware), "
            "and Internet Archive. Pin a system via extra_query_terms "
            "(e.g. system:N64 for Vimm, system:nintendo-snes for Edge)."
        ),
        "media_type": MediaType.GAME_ROM.value,
        "sources": [
            _src("vimm", 1.2),
            _src("edge_emulation", 1.0),
            # The three Chromium-driven sources (RomsFun, CDRomance,
            # MyAbandonware) each spin a real browser per grab — bump
            # their per-call timeout to 120 s.
            _src("romsfun", 0.9, timeout=120),
            _src("cdromance", 0.85, timeout=120),
            _src("myabandonware", 0.7, timeout=120),
            _src("internet_archive", 0.8, timeout=90),
        ],
        "filters": _filters(),
        "mode": ProfileMode.AGGREGATE_ALL.value,
        "newznab_categories": [1070],
    },
    {
        "slug": "papers_academic",
        "name": "Academic Papers",
        "description": "Academic papers via AA and LibGen scimag.",
        "media_type": MediaType.PAPER.value,
        "sources": [
            _src("anna_archive", 1.0),
            _src("libgen", 1.0),
        ],
        "filters": _filters(preferred_formats=["pdf"]),
        "mode": ProfileMode.FIRST_MATCH.value,
        "newznab_categories": [7060],
    },
    {
        "slug": "music_general",
        "name": "Music General",
        "description": "Aggregate-mode music search combining AA and Internet Archive's etree.",
        "media_type": MediaType.MUSIC.value,
        "sources": [
            _src("anna_archive", 1.0),
            _src("internet_archive", 0.9),
        ],
        "filters": _filters(preferred_formats=["flac", "mp3"]),
        "mode": ProfileMode.AGGREGATE_ALL.value,
        "newznab_categories": [3040],
    },
    {
        "slug": "comics_general",
        "name": "Comics General",
        "description": "Comics via AA, LibGen, and Internet Archive.",
        "media_type": MediaType.COMIC.value,
        "sources": [
            _src("anna_archive", 1.2),
            _src("libgen", 0.9),
            _src("internet_archive", 0.8),
        ],
        "filters": _filters(preferred_formats=["cbz", "cbr", "pdf"]),
        "mode": ProfileMode.FIRST_MATCH.value,
        "newznab_categories": [7030],
    },
]
