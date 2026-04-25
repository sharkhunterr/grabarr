"""Vendor-compat: ``bypass/fingerprint`` screen-size randomization (FR-040)."""

from __future__ import annotations

from grabarr.vendor.shelfmark.bypass.fingerprint import (
    COMMON_RESOLUTIONS,
    get_screen_size,
    rotate_screen_size,
)


def test_get_screen_size_returns_valid_tuple() -> None:
    width, height = get_screen_size()
    assert isinstance(width, int) and width > 0
    assert isinstance(height, int) and height > 0


def test_screen_size_rotates_through_pool() -> None:
    """``get_screen_size`` is sticky within a session; ``rotate_screen_size``
    picks a fresh one. Over many rotations we should see several distinct
    resolutions from ``COMMON_RESOLUTIONS``."""
    assert len(COMMON_RESOLUTIONS) >= 3
    seen = set()
    for _ in range(200):
        rotate_screen_size()
        seen.add(get_screen_size())
    assert len(seen) >= 3, (
        f"rotate_screen_size should draw from a pool of at least 3 "
        f"distinct values; saw {seen}"
    )
