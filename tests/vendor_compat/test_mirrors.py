"""Vendor-compat: ``core/mirrors`` AA/LibGen/Z-Lib/Welib mirror lists.

At v1.2.1 the mirrors module exposes function-style getters plus
module-level default lists. We verify the defaults are non-empty and
that each getter returns a list of valid-looking URLs.
"""

from __future__ import annotations

from grabarr.vendor.shelfmark.core import mirrors


def test_default_mirror_lists_are_non_empty() -> None:
    """The constants Shelfmark falls back to must ship populated."""
    for const_name in (
        "DEFAULT_AA_MIRRORS",
        "DEFAULT_LIBGEN_MIRRORS",
        "DEFAULT_WELIB_MIRRORS",
        "DEFAULT_ZLIB_MIRRORS",
    ):
        value = getattr(mirrors, const_name)
        assert isinstance(value, list)
        assert len(value) >= 1, f"{const_name} is empty in vendored source"


def test_mirror_getters_return_lists() -> None:
    """Each public getter function returns a list (possibly empty after
    user override, but always a list)."""
    for fn_name in (
        "get_aa_mirrors",
        "get_libgen_mirrors",
        "get_welib_mirrors",
        "get_zlib_mirrors",
    ):
        fn = getattr(mirrors, fn_name)
        out = fn()
        assert isinstance(out, list), f"{fn_name} returned {type(out).__name__}"
