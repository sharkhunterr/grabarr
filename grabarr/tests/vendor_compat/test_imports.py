"""Vendor-compat: every vendored file must import on Python 3.12.

This is the first line of defence against a broken vendor refresh.
If any import fails, the whole Grabarr cascade is DOA regardless of
whether the specific code path is exercised at runtime.
"""

from __future__ import annotations

import importlib

import pytest


# Core cascade + bypass modules — must import cleanly on every Python version
# Grabarr supports. SeleniumBase is marked as internal-bypasser optional
# extra; skip its import test when the extra isn't installed.
CORE_VENDORED_MODULES = [
    "grabarr.vendor.shelfmark",
    "grabarr.vendor.shelfmark._grabarr_adapter",
    "grabarr.vendor.shelfmark.bypass",
    "grabarr.vendor.shelfmark.bypass.external_bypasser",
    "grabarr.vendor.shelfmark.bypass.fingerprint",
    "grabarr.vendor.shelfmark.core.mirrors",
    "grabarr.vendor.shelfmark.core.naming",
    "grabarr.vendor.shelfmark.core.models",
    "grabarr.vendor.shelfmark.core.utils",
    "grabarr.vendor.shelfmark.release_sources.direct_download",
]


@pytest.mark.parametrize("module_name", CORE_VENDORED_MODULES)
def test_vendored_module_imports(module_name: str) -> None:
    """Every core vendored module imports without raising."""
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_direct_download_exposes_constitution_article_vii_invariants() -> None:
    """Constitution Article VII names these explicitly — they MUST survive a vendor refresh."""
    from grabarr.vendor.shelfmark.release_sources import direct_download

    # Failure threshold MUST be 4 per the Constitution.
    assert direct_download._SOURCE_FAILURE_THRESHOLD == 4

    # CF-bypass-required set must at least include the spec-named
    # sub-sources (ipfs was dropped upstream before v1.2.1; that's fine).
    required = direct_download._CF_BYPASS_REQUIRED
    for name in ("aa-slow-nowait", "aa-slow-wait", "zlib", "welib"):
        assert name in required, f"{name} should be in _CF_BYPASS_REQUIRED"

    # Sub-source taxonomy — constitution names aa-fast/aa-slow-nowait/
    # aa-slow-wait/aa-slow/libgen/zlib/welib. (ipfs is absent at v1.2.1.)
    sources = direct_download._DOWNLOAD_SOURCES
    # Data shape at v1.2.1 is a list of (id, display, markers) tuples.
    assert isinstance(sources, list)
    ids = {entry[0] for entry in sources}
    for expected in (
        "aa-fast",
        "aa-slow-wait",
        "aa-slow-nowait",
        "aa-slow",
        "libgen",
        "zlib",
        "welib",
    ):
        assert expected in ids, f"{expected} missing from vendored _DOWNLOAD_SOURCES"


def test_grabarr_adapter_proxy_has_expected_defaults() -> None:
    """The hand-authored shim MUST expose the keys Shelfmark reads eagerly."""
    from grabarr.vendor.shelfmark._grabarr_adapter import shelfmark_config_proxy

    # Attribute access style
    assert isinstance(shelfmark_config_proxy.SUPPORTED_FORMATS, list)
    assert "epub" in shelfmark_config_proxy.SUPPORTED_FORMATS

    # .get(key, default) dict style
    assert shelfmark_config_proxy.get("NONEXISTENT", 42) == 42
    assert shelfmark_config_proxy.get("AA_DONATOR_KEY", "fallback") in ("", "fallback")
