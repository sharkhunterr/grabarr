"""Newznab category codes.

Prowlarr's "Generic Torznab" indexer import expects category codes that
map to its own internal category tree (``IndexerCategory.cs``). Using any
other codes causes Prowlarr's test to fail (breaks SC-002 "all seven
profiles pass Prowlarr's test first try").

The table here is the minimum subset Grabarr emits — one row per default
profile plus the common alternatives operators are likely to use when
they build a custom profile.
"""

from __future__ import annotations

from grabarr.core.enums import MediaType


# Canonical Newznab categories we emit in Torznab ``<caps>``/``<item>``
# responses and accept in the Prowlarr export. Keys are integer codes per
# the Newznab spec; values are the human-readable names Prowlarr displays.
NEWZNAB_CATEGORIES: dict[int, str] = {
    # Audio
    3000: "Audio",
    3010: "Audio/MP3",
    3020: "Audio/Video",
    3030: "Audio/Audiobook",
    3040: "Audio/Lossless",
    3050: "Audio/Other",
    # PC / software / ROMs
    1000: "PC",
    1010: "PC/0day",
    1020: "PC/ISO",
    1030: "PC/Mac",
    1040: "PC/Mobile",
    1050: "PC/Games",
    1060: "PC/Games/Wii",
    1070: "PC/Games/Xbox",
    # Books (the 7xxx space is the Torznab "book" family)
    7000: "Books",
    7020: "Books/EBook",
    7030: "Books/Comics",
    7040: "Books/Magazines",
    7050: "Books/Technical",
    7060: "Books/Other",
    7070: "Books/Foreign",
    # Movies (for the rare v1.0 profile that ships for video)
    2000: "Movies",
    2040: "Movies/HD",
    # Other
    0: "Other",
}


# Mapping from our MediaType to the default Newznab category list that
# ``grabarr/profiles/defaults.py`` seeds into the seven default profiles.
DEFAULT_CATEGORIES: dict[MediaType, list[int]] = {
    MediaType.EBOOK: [7020],
    MediaType.AUDIOBOOK: [3030],
    MediaType.COMIC: [7030],
    MediaType.MAGAZINE: [7040],
    MediaType.MUSIC: [3040],
    MediaType.SOFTWARE: [1000],
    MediaType.PAPER: [7060],
    MediaType.GAME_ROM: [1070],
    MediaType.VIDEO: [2000],
}


def category_name(code: int) -> str:
    """Return Prowlarr's expected display name for ``code`` (or empty)."""
    return NEWZNAB_CATEGORIES.get(code, "")
