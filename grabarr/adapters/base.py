"""Canonical ``SourceAdapter`` protocol and error hierarchy.

Mirrors ``specs/001-grabarr-core-platform/contracts/source-adapter.py``
exactly. The contracts file is the source of truth; this module is the
runtime re-export that adapters import. Changes here require matching
changes in the contract.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from grabarr.core.enums import MediaType
from grabarr.core.models import (
    ConfigField,
    ConfigSchema,
    DownloadInfo,
    HealthStatus,
    QuotaStatus,
    SearchFilters,
    SearchResult,
)

__all__ = [
    "AdapterAuthError",
    "AdapterBypassError",
    "AdapterConnectivityError",
    "AdapterError",
    "AdapterNotFound",
    "AdapterQuotaError",
    "AdapterRateLimitError",
    "AdapterServerError",
    "ConfigField",
    "ConfigSchema",
    "DownloadInfo",
    "HealthStatus",
    "MediaType",
    "QuotaStatus",
    "SearchFilters",
    "SearchResult",
    "SourceAdapter",
]


@runtime_checkable
class SourceAdapter(Protocol):
    """Every file in ``grabarr/adapters/`` implements this."""

    # ---- static metadata (class-level) --------------------------------

    id: str
    display_name: str
    supported_media_types: set[MediaType]
    requires_cf_bypass: bool
    supports_member_key: bool
    supports_authentication: bool

    # ---- primary API ---------------------------------------------------

    async def search(
        self,
        query: str,
        media_type: MediaType,
        filters: SearchFilters,
        limit: int = 50,
    ) -> list[SearchResult]: ...

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
        query_hint: str | None = None,
    ) -> DownloadInfo: ...

    async def health_check(self) -> HealthStatus: ...

    def get_config_schema(self) -> ConfigSchema: ...

    async def get_quota_status(self) -> QuotaStatus | None: ...


# ---- Exceptions ---------------------------------------------------------


class AdapterError(Exception):
    """Base class for every adapter-raised error."""


class AdapterConnectivityError(AdapterError):
    """Transport layer failed (DNS, TCP, TLS, timeout before body)."""


class AdapterBypassError(AdapterError):
    """Cloudflare or bypass pipeline failed."""


class AdapterAuthError(AdapterError):
    """Cookies expired or credentials invalid (e.g. Z-Library cookie)."""


class AdapterQuotaError(AdapterError):
    """Source-imposed quota reached (e.g. Z-Library daily limit)."""


class AdapterRateLimitError(AdapterError):
    """Source returned 429, or the local token bucket drained."""


class AdapterServerError(AdapterError):
    """5xx response from the source."""


class AdapterNotFound(AdapterError):
    """The external ID no longer resolves to a real item."""
