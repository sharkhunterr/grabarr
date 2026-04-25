"""Vendor-compat: ``bypass/external_bypasser`` surface.

At v1.2.1 the module exports ``get_bypassed_page`` — the function the
vendored cascade calls when FlareSolverr is needed. We only verify the
module loads and that symbol exists; a protocol-level test would
duplicate Shelfmark's own upstream test suite.
"""

from __future__ import annotations

from grabarr.vendor.shelfmark.bypass import external_bypasser


def test_external_bypasser_exposes_get_bypassed_page() -> None:
    assert callable(external_bypasser.get_bypassed_page), (
        "vendored external_bypasser.py must export get_bypassed_page"
    )


def test_external_bypasser_declares_timeout_constants() -> None:
    """Constitution Article VIII's 'logic untouched' rule means the
    upstream retry + timeout constants must survive the import rewrite."""
    for name in (
        "MAX_RETRY",
        "BACKOFF_BASE",
        "BACKOFF_CAP",
        "CONNECT_TIMEOUT",
        "MAX_READ_TIMEOUT",
        "READ_TIMEOUT_BUFFER",
    ):
        assert hasattr(external_bypasser, name), f"missing constant {name}"
        assert isinstance(getattr(external_bypasser, name), (int, float))
