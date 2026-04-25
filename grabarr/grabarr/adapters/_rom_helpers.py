"""Shared helpers for the ROM-source adapters.

Centralised so each adapter (Vimm, Edge, RomsFun, CDRomance,
MyAbandonware) keeps the same scoring + settings-overlay logic.
"""

from __future__ import annotations

import json
import re
from typing import Any

from grabarr.core.logging import setup_logger
from grabarr.core.settings_service import get_sync

_log = setup_logger(__name__)


def score_title_relevance(title: str, query: str) -> float:
    """Return a relevance bonus (0–60) for ``title`` against ``query``.

    Tiered: exact title equality > full substring > token-overlap. The
    base of 50.0 lives on the SearchResult; this function returns the
    DELTA to add. Negative values (e.g. for Hack/Pirate variants) are
    applied separately by adapters.

      +60: case-insensitive exact title match
      +35: query is a substring of the title (or vice versa)
      +N : N points per overlapping token (cap +20)
    """
    if not query or not title:
        return 0.0
    t_low = title.lower()
    q_low = query.lower().strip()
    if t_low == q_low:
        return 60.0
    if q_low in t_low or t_low in q_low:
        return 35.0
    # Token overlap fallback.
    title_tokens = {tk for tk in re.split(r"[^a-z0-9]+", t_low) if len(tk) > 1}
    query_tokens = {tk for tk in re.split(r"[^a-z0-9]+", q_low) if len(tk) > 1}
    overlap = len(title_tokens & query_tokens)
    if overlap == 0:
        return 0.0
    # 8 points per token overlap, capped at +20 (e.g. 3 shared tokens).
    return float(min(20, overlap * 8))


def settings_overlay(
    setting_key: str,
    builtin: dict[str, Any],
) -> dict[str, Any]:
    """Merge a JSON-encoded operator override on top of a builtin map.

    The settings table stores ``setting_key`` as a TEXT cell; ops paste
    a JSON object via the Settings UI to extend or rewrite the built-in
    entries (per-system labels, region maps, size estimates, etc.).
    Invalid JSON is logged + ignored — built-in still wins.

    Returns ``{**builtin, **operator_overrides}``.
    """
    raw = (get_sync(setting_key, "") or "").strip()
    if not raw:
        return dict(builtin)
    try:
        overlay = json.loads(raw)
    except (ValueError, TypeError) as exc:
        _log.warning(
            "settings_overlay: %s is not valid JSON (%s); using builtin only",
            setting_key, exc,
        )
        return dict(builtin)
    if not isinstance(overlay, dict):
        _log.warning(
            "settings_overlay: %s decoded as %s, expected dict; using builtin",
            setting_key, type(overlay).__name__,
        )
        return dict(builtin)
    merged = dict(builtin)
    merged.update(overlay)
    return merged
