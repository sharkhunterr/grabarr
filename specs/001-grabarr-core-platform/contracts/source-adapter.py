"""
Grabarr SourceAdapter Protocol — CONTRACT ONLY

This file is the CANONICAL definition of the contract that every adapter
under `grabarr/adapters/` MUST implement. It is kept in `specs/.../contracts/`
as the authoritative source; the runtime `grabarr/adapters/base.py` MUST
mirror these signatures exactly.

Adding a new source = one file in `grabarr/adapters/<source_id>.py` that
implements this protocol and is decorated with `@register_adapter`.

See: spec.md §FR-002, FR-007, FR-008.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable


# ----- shared enums -------------------------------------------------------


class MediaType(StrEnum):
    EBOOK = "ebook"
    AUDIOBOOK = "audiobook"
    COMIC = "comic"
    MAGAZINE = "magazine"
    MUSIC = "music"
    SOFTWARE = "software"
    PAPER = "paper"
    GAME_ROM = "game_rom"
    VIDEO = "video"


class AdapterHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class UnhealthyReason(StrEnum):
    CONNECTIVITY = "connectivity"
    BYPASS_FAILED = "bypass_failed"
    FLARESOLVERR_DOWN = "flaresolverr_down"
    COOKIE_EXPIRED = "cookie_expired"
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR_5XX = "server_error_5xx"


# ----- shared dataclasses -------------------------------------------------


@dataclass(frozen=True)
class SearchFilters:
    languages: list[str]
    preferred_formats: list[str]
    min_year: int | None
    max_year: int | None
    min_size_mb: float | None
    max_size_mb: float | None
    require_isbn: bool
    extra_query_terms: str


@dataclass(frozen=True)
class SearchResult:
    external_id: str
    title: str
    author: str | None
    year: int | None
    format: str
    language: str | None
    size_bytes: int | None
    quality_score: float
    source_id: str
    media_type: MediaType
    metadata: dict[str, Any]


@dataclass(frozen=True)
class DownloadInfo:
    """Everything the DownloadManager needs to fetch the bytes.

    Adapter implementations may return this immediately for direct-URL
    sources (IA) or only after exhausting the cascade (AA/LibGen/Z-Lib).
    """
    download_url: str
    size_bytes: int | None
    content_type: str | None
    filename_hint: str
    extra_headers: dict[str, str]


@dataclass(frozen=True)
class HealthStatus:
    status: AdapterHealth
    reason: UnhealthyReason | None
    message: str | None
    checked_at: datetime


@dataclass(frozen=True)
class QuotaStatus:
    used: int
    limit: int
    resets_at: datetime


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    field_type: Literal["text", "password", "int", "bool", "select"]
    options: list[str] | None
    secret: bool
    required: bool
    help_text: str | None


@dataclass(frozen=True)
class ConfigSchema:
    fields: list[ConfigField]


# ----- the protocol itself ------------------------------------------------


@runtime_checkable
class SourceAdapter(Protocol):
    """The sole interface the orchestrator calls against."""

    # --- metadata (class-level attributes) ---

    id: str                              # snake_case; unique; used as FK
    display_name: str                    # human-readable
    supported_media_types: set[MediaType]
    requires_cf_bypass: bool
    supports_member_key: bool
    supports_authentication: bool        # Z-Library cookie-style

    # --- primary API ---

    async def search(
        self,
        query: str,
        media_type: MediaType,
        filters: SearchFilters,
        limit: int = 50,
    ) -> list[SearchResult]:
        """Return up to `limit` normalized results.

        MUST respect `filters` on the adapter side where the source supports
        filtering natively. Results not fitting `filters` MAY pass through if
        the source cannot filter (the orchestrator will drop them).

        MUST raise `AdapterError` subclasses on transport failures; the
        orchestrator treats those as degradation signals for the circuit
        breaker.
        """
        ...

    async def get_download_info(
        self,
        external_id: str,
        media_type: MediaType,
        query_hint: str | None = None,
    ) -> DownloadInfo:
        """Resolve a `SearchResult.external_id` to a concrete download URL.

        For cascading adapters (AA/LibGen/Z-Lib) this MAY loop through sub-
        sources until one yields a URL; implementations MUST respect the
        vendored Shelfmark failure-threshold semantics (4 consecutive
        failures → next sub-source).

        ``query_hint`` is the original Torznab `q=` value the user (or
        Bookshelf/Readarr) submitted at search time, threaded through
        ``search_tokens.query`` and ``downloads.query``. Adapters MAY use
        it to disambiguate the file inside a multi-file item — most
        notably the IA adapter, where a "no-intro" romset identifier
        like ``nointro.snes`` resolves to thousands of ZIPs and only the
        query disambiguates which one. Optional; pass ``None`` when no
        hint is available. Adapters MUST NOT raise on missing hint.
        """
        ...

    async def health_check(self) -> HealthStatus:
        """Probe the source cheaply.

        MUST NOT consume quota where a rate-limited source has an out-of-band
        health endpoint. Callers treat non-healthy returns as circuit-breaker
        inputs (see FR-036).
        """
        ...

    def get_config_schema(self) -> ConfigSchema:
        """Describe this adapter's config to the Sources UI.

        Return value is rendered as the expandable config pane on
        `/sources`. Keys MUST be namespaced as
        `sources.<adapter_id>.<field_key>` (dot-path).
        """
        ...

    async def get_quota_status(self) -> QuotaStatus | None:
        """Return current quota or `None` if the source is unlimited.

        Z-Library returns a real value; AA/LibGen/IA return `None`.
        """
        ...


# ----- the error hierarchy ------------------------------------------------


class AdapterError(Exception):
    """Base class. Every adapter-raised error MUST subclass this."""


class AdapterConnectivityError(AdapterError):
    """Network layer failed."""


class AdapterBypassError(AdapterError):
    """Cloudflare / bypass pipeline failed."""


class AdapterAuthError(AdapterError):
    """Cookies expired / credentials invalid."""


class AdapterQuotaError(AdapterError):
    """Source-imposed quota reached."""


class AdapterRateLimitError(AdapterError):
    """Source returned 429 or our local token bucket emptied."""


class AdapterServerError(AdapterError):
    """5xx from the source."""


class AdapterNotFound(AdapterError):
    """External ID no longer resolvable."""


# ----- the registry decorator ---------------------------------------------


def register_adapter(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """Register the adapter class with the global registry.

    The registry is populated at startup by `grabarr.core.registry`
    importing every submodule of `grabarr.adapters.*` — no manual list is
    maintained.
    """
    # Implementation lives in grabarr/adapters/__init__.py.
    ...
