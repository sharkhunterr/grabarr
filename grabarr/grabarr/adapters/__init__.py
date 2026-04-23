"""Grabarr source adapters.

Importing this package triggers :func:`discover_adapters`, which walks
every submodule whose name does not start with ``_`` and imports it.
``@register_adapter`` calls inside those modules populate the registry
defined in :mod:`grabarr.core.registry`.

Adding a new adapter is therefore a single file here with
``@register_adapter`` on the class — no other wiring needed (spec SC-08,
Constitution §IV).
"""

from __future__ import annotations

from grabarr.core.registry import (
    discover_adapters,
    get_adapter_by_id,
    get_registered_adapters,
    register_adapter,
)

__all__ = [
    "discover_adapters",
    "get_adapter_by_id",
    "get_registered_adapters",
    "register_adapter",
]


# Trigger discovery exactly once when this package is first imported.
discover_adapters(__name__)
