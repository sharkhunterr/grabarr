"""Vendored Shelfmark modules.

See ``ATTRIBUTION.md`` in this directory for upstream source, license, pinned
commit SHA, and vendoring date. The only hand-authored file in this
subtree is ``_grabarr_adapter.py`` which bridges Shelfmark's config/logger
imports onto Grabarr's equivalents. Every other file is a verbatim copy
from upstream at the pinned commit, with only import-path rewrites
applied per Constitution §III.

Importing this package eagerly loads ``_grabarr_adapter`` so that
downstream ``from grabarr.vendor.shelfmark._grabarr_adapter import
shelfmark_config_proxy as config`` statements resolve correctly regardless
of import order.
"""

from grabarr.vendor.shelfmark import _grabarr_adapter  # noqa: F401

__all__: list[str] = []
