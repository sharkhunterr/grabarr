"""Shared fixtures for the vendor-compat suite."""

from __future__ import annotations

import pytest
import respx


@pytest.fixture
def respx_mock() -> respx.Router:
    """Per-test respx router (not a context manager — explicit start/stop)."""
    with respx.mock(assert_all_called=False) as router:
        yield router
