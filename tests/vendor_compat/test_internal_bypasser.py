"""Vendor-compat: ``bypass/internal_bypasser`` import smoke test.

The internal bypasser uses SeleniumBase which is an optional dependency
(``pip install grabarr[internal-bypasser]``). If SeleniumBase isn't
installed we simply skip — that's the expected state in a default
install per the Clarifications session (external bypass mode).
"""

from __future__ import annotations

import importlib.util

import pytest


def test_internal_bypasser_imports_if_selenium_available() -> None:
    if importlib.util.find_spec("seleniumbase") is None:
        pytest.skip("seleniumbase not installed — optional extra")

    import grabarr.vendor.shelfmark.bypass.internal_bypasser as ib  # noqa: F401
