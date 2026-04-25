"""Domain enums used across Grabarr.

Every enum is a ``StrEnum`` so values round-trip through JSON and SQLite
TEXT columns without any custom serializer. The values are the source of
truth for the database schema's CHECK constraints (see
``grabarr/db/migrations/versions/``).
"""

from __future__ import annotations

from enum import StrEnum


class MediaType(StrEnum):
    """Kinds of content a profile can route (Constitution Article V)."""

    EBOOK = "ebook"
    AUDIOBOOK = "audiobook"
    COMIC = "comic"
    MAGAZINE = "magazine"
    MUSIC = "music"
    SOFTWARE = "software"
    PAPER = "paper"
    GAME_ROM = "game_rom"
    VIDEO = "video"


class DownloadMode(StrEnum):
    """How the HTTP download is scheduled relative to the torrent hand-off.

    ``SYNC`` is the shipping default per the Clarifications session.
    """

    SYNC = "sync"
    ASYNC_STREAMING = "async_streaming"
    HYBRID = "hybrid"


class TorrentMode(StrEnum):
    """How the `.torrent` is generated and served.

    ``ACTIVE_SEED`` is the shipping default per Constitution Article IX.
    """

    ACTIVE_SEED = "active_seed"
    WEBSEED = "webseed"


class BypassMode(StrEnum):
    """Cloudflare-bypass dispatcher mode.

    ``EXTERNAL`` (FlareSolverr sidecar) is the shipping default per the
    Clarifications session. ``INTERNAL`` uses the vendored SeleniumBase
    bypasser; ``AUTO`` tries external first, falls back to internal.
    """

    EXTERNAL = "external"
    INTERNAL = "internal"
    AUTO = "auto"


class ProfileMode(StrEnum):
    """Orchestrator behaviour across a profile's source list."""

    FIRST_MATCH = "first_match"
    AGGREGATE_ALL = "aggregate_all"


class DownloadStatus(StrEnum):
    """Lifecycle of a single grab request.

    Linear happy path: QUEUED → RESOLVING → DOWNLOADING → VERIFYING → READY
    → SEEDING → COMPLETED. Any state may jump to FAILED.
    """

    QUEUED = "queued"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    READY = "ready"
    SEEDING = "seeding"
    COMPLETED = "completed"
    FAILED = "failed"


class AdapterHealth(StrEnum):
    """Circuit-breaker state for a source adapter (FR-036)."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class UnhealthyReason(StrEnum):
    """Why an adapter is not healthy. Surfaces in UI + notifications."""

    CONNECTIVITY = "connectivity"
    BYPASS_FAILED = "bypass_failed"
    FLARESOLVERR_DOWN = "flaresolverr_down"
    COOKIE_EXPIRED = "cookie_expired"
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR_5XX = "server_error_5xx"


class NotificationEvent(StrEnum):
    """Catalogue of events that fan out to Apprise / webhook (FR-031)."""

    DOWNLOAD_COMPLETED = "download_completed"
    DOWNLOAD_FAILED = "download_failed"
    SOURCE_UNHEALTHY = "source_unhealthy"
    SOURCE_RECOVERED = "source_recovered"
    QUOTA_EXHAUSTED = "quota_exhausted"
    BYPASS_FAILED = "bypass_failed"
    COOKIE_EXPIRED = "cookie_expired"


class NotificationSeverity(StrEnum):
    """Per-event severity tag for the notification payload."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NotificationDispatchStatus(StrEnum):
    """Outcome of a notification dispatch attempt (stored in the log)."""

    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"  # coalesced by flap suppression (FR-031a)
