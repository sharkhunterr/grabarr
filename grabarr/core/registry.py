"""Adapter auto-discovery registry.

Per Constitution Article IV and spec FR-007, every file under
``grabarr/adapters/`` that declares ``@register_adapter`` is picked up
automatically at startup — no hand-edited global list.

Usage (inside an adapter file):

.. code-block:: python

    from grabarr.core.registry import register_adapter
    from grabarr.adapters.base import SourceAdapter

    @register_adapter
    class InternetArchiveAdapter:       # conforms to SourceAdapter
        id = "internet_archive"
        ...

After import the class is available via :func:`get_registered_adapters`
and :func:`get_adapter_by_id`.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, TypeVar

from grabarr.core.logging import setup_logger

if TYPE_CHECKING:
    from grabarr.adapters.base import SourceAdapter

_log = setup_logger(__name__)

AdapterClassT = TypeVar("AdapterClassT", bound=type)

_REGISTRY: dict[str, type] = {}


def register_adapter(cls: AdapterClassT) -> AdapterClassT:
    """Decorator that registers a class by its ``id`` attribute.

    Duplicate IDs raise ``ValueError`` at import time so typos are caught
    deterministically.
    """
    source_id = getattr(cls, "id", None)
    if not isinstance(source_id, str) or not source_id:
        raise ValueError(
            f"@register_adapter: {cls.__name__} must declare a non-empty "
            "class attribute `id: str`"
        )
    if source_id in _REGISTRY and _REGISTRY[source_id] is not cls:
        raise ValueError(
            f"@register_adapter: duplicate adapter id {source_id!r} "
            f"(existing={_REGISTRY[source_id].__module__}, "
            f"new={cls.__module__})"
        )
    _REGISTRY[source_id] = cls
    _log.debug("registered adapter %s from %s", source_id, cls.__module__)
    return cls


def discover_adapters(package: str = "grabarr.adapters") -> None:
    """Import every submodule of ``package`` so decorators fire.

    Called once at startup by ``grabarr/adapters/__init__.py``. Safe to
    re-invoke; already-imported modules are skipped by Python's import
    cache and ``@register_adapter`` is idempotent for the same class.

    Submodules whose name starts with ``_`` (e.g. ``_welib_template``)
    are skipped — that naming convention marks templates and examples.
    """
    pkg = importlib.import_module(package)
    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        return
    for info in pkgutil.iter_modules(pkg_path):
        if info.name.startswith("_"):
            continue
        if info.name in {"base", "health_model", "zlibrary_quota_model"}:
            # "base" is imported lazily by every adapter; the *_model
            # modules are ORM glue, not adapter classes.
            continue
        importlib.import_module(f"{package}.{info.name}")


def get_registered_adapters() -> dict[str, type[SourceAdapter]]:
    """Return a copy of the id → class mapping."""
    return dict(_REGISTRY)


def get_adapter_by_id(source_id: str) -> type[SourceAdapter] | None:
    """Return the adapter class registered for ``source_id``, or None."""
    return _REGISTRY.get(source_id)


def clear_registry() -> None:
    """Test-only: wipe the registry (used by `tests/fixtures/adapters/`).

    Calling this in production is almost certainly wrong — the registry
    is a process-wide singleton by design.
    """
    _REGISTRY.clear()
