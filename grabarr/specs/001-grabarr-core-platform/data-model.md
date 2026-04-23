# Phase 1 — Data Model

**Feature**: 001-grabarr-core-platform
**Date**: 2026-04-23

All persistent state lives in a single SQLite database accessed via SQLAlchemy
2.0 async. Migrations are managed by Alembic and run at every startup
(FR-038). JSON columns are stored as TEXT and de/serialized via
`sqlalchemy.JSON` type.

Types use Python 3.12+ syntax in the table descriptions for brevity. "UUIDv7"
means a time-ordered UUID (e.g. via `uuid_utils.uuid7()`); we prefer UUIDv7
for primary keys on high-insert tables so B-tree indexes stay append-
friendly.

---

## Enums

### MediaType

```python
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
```

### DownloadMode / TorrentMode / BypassMode

```python
class DownloadMode(StrEnum):
    SYNC = "sync"                      # shipping default (per clarifications)
    ASYNC_STREAMING = "async_streaming"
    HYBRID = "hybrid"

class TorrentMode(StrEnum):
    ACTIVE_SEED = "active_seed"        # shipping default (Constitution IX)
    WEBSEED = "webseed"

class BypassMode(StrEnum):
    EXTERNAL = "external"              # shipping default (per clarifications)
    INTERNAL = "internal"
    AUTO = "auto"
```

### ProfileOrchestrationMode

```python
class ProfileMode(StrEnum):
    FIRST_MATCH = "first_match"
    AGGREGATE_ALL = "aggregate_all"
```

### DownloadStatus

```python
class DownloadStatus(StrEnum):
    QUEUED = "queued"
    RESOLVING = "resolving"    # adapter.get_download_info() in-flight
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"    # magic-byte / size checks
    READY = "ready"            # file on disk, torrent generated
    SEEDING = "seeding"
    COMPLETED = "completed"    # retention window elapsed OR *arr confirmed pull
    FAILED = "failed"
```

State transitions (linear happy path — failure may jump to `FAILED` from any
prior state):

```text
QUEUED → RESOLVING → DOWNLOADING → VERIFYING → READY → SEEDING → COMPLETED
                                                                  ↑
                                                               FAILED
```

### AdapterHealthStatus

```python
class AdapterHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"      # transient failures, not yet unhealthy
    UNHEALTHY = "unhealthy"    # circuit breaker tripped
```

### AdapterUnhealthyReason

```python
class UnhealthyReason(StrEnum):
    CONNECTIVITY = "connectivity"
    BYPASS_FAILED = "bypass_failed"
    FLARESOLVERR_DOWN = "flaresolverr_down"
    COOKIE_EXPIRED = "cookie_expired"
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR_5XX = "server_error_5xx"
```

### NotificationEventType

```python
class NotificationEvent(StrEnum):
    DOWNLOAD_COMPLETED = "download_completed"
    DOWNLOAD_FAILED = "download_failed"
    SOURCE_UNHEALTHY = "source_unhealthy"
    SOURCE_RECOVERED = "source_recovered"
    QUOTA_EXHAUSTED = "quota_exhausted"
    BYPASS_FAILED = "bypass_failed"
    COOKIE_EXPIRED = "cookie_expired"
```

---

## Tables

### `profiles`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | UUIDv7 | PK | |
| `slug` | TEXT | UNIQUE NOT NULL, regex `^[a-z0-9][a-z0-9_-]{1,63}$` | URL-safe; used in `/torznab/{slug}/api` |
| `name` | TEXT | NOT NULL | Human-readable |
| `description` | TEXT | nullable | |
| `media_type` | TEXT | NOT NULL (FK to `MediaType` enum via CHECK) | |
| `sources` | JSON | NOT NULL | Ordered `list[SourcePriorityEntry]` |
| `filters` | JSON | NOT NULL | `SearchFilters` dict |
| `mode` | TEXT | NOT NULL | `first_match` \| `aggregate_all` |
| `newznab_categories` | JSON | NOT NULL | `list[int]`; Prowlarr caps |
| `download_mode_override` | TEXT | nullable | Any `DownloadMode`; null = global default |
| `torrent_mode_override` | TEXT | nullable | Any `TorrentMode`; null = global default |
| `enabled` | BOOLEAN | NOT NULL DEFAULT TRUE | |
| `api_key_hash` | TEXT | NOT NULL | bcrypt of the per-profile Torznab API key |
| `is_default` | BOOLEAN | NOT NULL DEFAULT FALSE | Seeded defaults cannot be deleted |
| `created_at` | TIMESTAMP WITH TZ | NOT NULL DEFAULT NOW | |
| `updated_at` | TIMESTAMP WITH TZ | NOT NULL DEFAULT NOW | |

**Indexes**: `UNIQUE(slug)`; `INDEX(enabled, is_default)`.

**Validation** (FR-011, FR-012):
- `slug` MUST be URL-safe and ≤ 64 chars.
- `is_default = TRUE` rows MUST NOT be deleted (enforced at service layer).
- Each `SourcePriorityEntry.weight` ∈ [0.1, 2.0].
- `SearchFilters.min_year ≤ max_year` when both present.
- `SearchFilters.min_size_mb ≤ max_size_mb` when both present.

**Embedded JSON shapes**:

```python
class SourcePriorityEntry(TypedDict):
    source_id: str            # adapter id (e.g. "anna_archive")
    weight: float             # 0.1 ≤ weight ≤ 2.0
    timeout_seconds: int      # > 0
    enabled: bool
    skip_if_member_required: bool

class SearchFilters(TypedDict):
    languages: list[str]             # ISO 639-1 codes; empty = any
    preferred_formats: list[str]     # e.g. ["epub", "mobi"]
    min_year: int | None
    max_year: int | None
    min_size_mb: float | None
    max_size_mb: float | None
    require_isbn: bool
    extra_query_terms: str           # appended to the user query
```

---

### `settings`

Single-row-per-key key-value store for UI-mutable settings (per R-8).

| Column | Type | Constraints |
|--------|------|-------------|
| `key` | TEXT | PK |
| `value` | JSON | NOT NULL |
| `updated_at` | TIMESTAMP WITH TZ | NOT NULL DEFAULT NOW |

Canonical keys (enforced via application-level allowlist):

| Key | Value shape | Default |
|-----|-------------|---------|
| `download.mode` | `"sync" \| "async_streaming" \| "hybrid"` | `"sync"` |
| `download.hybrid_threshold_mb` | `int` | `50` |
| `download.timeout_seconds` | `int` | `300` |
| `download.max_size_gb` | `float` | `5.0` |
| `torrent.mode` | `"active_seed" \| "webseed"` | `"active_seed"` |
| `torrent.tracker_port` | `int` | `8999` |
| `torrent.listen_port_min` | `int` | `45000` |
| `torrent.listen_port_max` | `int` | `45100` |
| `torrent.seed_retention_hours` | `int` | `24` |
| `torrent.max_concurrent_seeds` | `int` | `100` |
| `bypass.mode` | `"external" \| "internal" \| "auto"` | `"external"` |
| `bypass.flaresolverr_url` | `str` | `"http://flaresolverr:8191/v1"` |
| `bypass.session_cache_ttl_min` | `int` | `30` |
| `rate_limit.anna_archive.search_per_min` | `int` | `30` |
| `rate_limit.libgen.requests_per_min` | `int` | `60` |
| `rate_limit.zlibrary.requests_per_min` | `int` | `10` |
| `rate_limit.zlibrary.daily_quota` | `int` | `10` |
| `rate_limit.internet_archive.requests_per_min` | `int` | `30` |
| `metadata.ia_contact_email` | `str` | `""` (operator MUST set) |
| `metadata.user_agent_suffix` | `str` | `""` |
| `paths.output_template.<media_type>` | `str` | See R-13 |
| `notifications.flap_cooldown_minutes` | `int` | `10` |

---

### `downloads`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUIDv7 | PK |
| `token` | TEXT | UNIQUE NOT NULL (48-char URL-safe) |
| `profile_id` | UUIDv7 | FK → `profiles(id)` ON DELETE RESTRICT |
| `source_id` | TEXT | NOT NULL (adapter id) |
| `external_id` | TEXT | NOT NULL (e.g. AA md5, IA identifier) |
| `media_type` | TEXT | NOT NULL |
| `download_mode` | TEXT | NOT NULL (resolved at grab-time) |
| `torrent_mode` | TEXT | NOT NULL |
| `title` | TEXT | NOT NULL |
| `author` | TEXT | nullable |
| `year` | INT | nullable |
| `filename` | TEXT | NOT NULL (post-sanitization) |
| `size_bytes` | INTEGER | nullable (known for sync/hybrid, may be known at start for async) |
| `content_type` | TEXT | nullable |
| `magic_verified` | BOOLEAN | NOT NULL DEFAULT FALSE |
| `file_path` | TEXT | nullable (set when READY; cleared when file deleted) |
| `info_hash` | TEXT | nullable (set when torrent is generated; 40-char hex) |
| `status` | TEXT | NOT NULL (see `DownloadStatus`) |
| `failure_reason` | TEXT | nullable (populated on FAILED) |
| `started_at` | TIMESTAMP WITH TZ | NOT NULL DEFAULT NOW |
| `resolved_at` | TIMESTAMP WITH TZ | nullable |
| `ready_at` | TIMESTAMP WITH TZ | nullable |
| `seeded_at` | TIMESTAMP WITH TZ | nullable |
| `completed_at` | TIMESTAMP WITH TZ | nullable |
| `file_removed_at` | TIMESTAMP WITH TZ | nullable |

**Indexes**: `UNIQUE(token)`; `INDEX(profile_id, status)`;
`INDEX(started_at DESC)` for history pagination; `UNIQUE(info_hash)` when not
NULL.

**Retention**: The row is kept for 30 days from `started_at` (FR-039). The
physical `file_path` is cleared and the file removed when `ready_at +
settings.torrent.seed_retention_hours` has elapsed (FR-039a).

**State invariants**:
- `status = READY` ⇒ `file_path NOT NULL AND magic_verified = TRUE`.
- `status IN (SEEDING, COMPLETED)` ⇒ `info_hash NOT NULL`.
- `status = COMPLETED` ⇒ `completed_at NOT NULL`.
- `file_removed_at NOT NULL` ⇒ `status = COMPLETED AND file_path IS NULL`.

---

### `torrents`

The libtorrent session persists its own state blob (`/data/session.state`),
but we also keep per-torrent metadata for UI and observability.

| Column | Type | Constraints |
|--------|------|-------------|
| `info_hash` | TEXT | PK (40-char hex) |
| `download_id` | UUIDv7 | UNIQUE FK → `downloads(id)` ON DELETE CASCADE |
| `mode` | TEXT | NOT NULL (`active_seed` \| `webseed`) |
| `total_size_bytes` | INTEGER | NOT NULL |
| `piece_size_bytes` | INTEGER | NOT NULL |
| `piece_count` | INTEGER | NOT NULL |
| `webseed_url` | TEXT | nullable (set for `webseed`) |
| `generated_at` | TIMESTAMP WITH TZ | NOT NULL DEFAULT NOW |
| `expires_at` | TIMESTAMP WITH TZ | NOT NULL (generated_at + retention_hours) |
| `last_announced_at` | TIMESTAMP WITH TZ | nullable |

**Indexes**: `INDEX(expires_at)` for the cleanup sweeper.

---

### `tracker_peers`

The internal HTTP tracker's peer table. Peers are ephemeral; entries older
than 30 min are purged.

| Column | Type | Constraints |
|--------|------|-------------|
| `info_hash` | TEXT | NOT NULL (FK logically → `torrents`, but not enforced to allow early announce) |
| `peer_id` | TEXT | NOT NULL (20-byte as URL-escaped hex) |
| `ip` | TEXT | NOT NULL |
| `port` | INTEGER | NOT NULL |
| `last_seen_at` | TIMESTAMP WITH TZ | NOT NULL |
| `uploaded` | INTEGER | NOT NULL DEFAULT 0 |
| `downloaded` | INTEGER | NOT NULL DEFAULT 0 |
| `left_bytes` | INTEGER | NOT NULL DEFAULT 0 |
| `event` | TEXT | nullable (`started` \| `stopped` \| `completed`) |

**Primary key**: `(info_hash, peer_id)`.

---

### `bypass_sessions`

Bypass cache (R-5).

| Column | Type | Constraints |
|--------|------|-------------|
| `domain` | TEXT | PK |
| `user_agent` | TEXT | NOT NULL |
| `cf_clearance` | TEXT | NOT NULL |
| `issued_at` | TIMESTAMP WITH TZ | NOT NULL |
| `expires_at` | TIMESTAMP WITH TZ | NOT NULL |
| `mode_used` | TEXT | NOT NULL (`external` \| `internal`) |
| `hit_count` | INTEGER | NOT NULL DEFAULT 0 |

**Indexes**: `INDEX(expires_at)` for the sweeper.

---

### `adapter_health`

Rolling health snapshot per adapter. One row per adapter, updated in place.

| Column | Type | Constraints |
|--------|------|-------------|
| `adapter_id` | TEXT | PK |
| `status` | TEXT | NOT NULL (`healthy` \| `degraded` \| `unhealthy`) |
| `reason` | TEXT | nullable (`UnhealthyReason`) |
| `last_check_at` | TIMESTAMP WITH TZ | NOT NULL |
| `next_recheck_at` | TIMESTAMP WITH TZ | NOT NULL |
| `consecutive_failures` | INTEGER | NOT NULL DEFAULT 0 |
| `last_success_at` | TIMESTAMP WITH TZ | nullable |
| `last_error_message` | TEXT | nullable (redacted) |

**Circuit breaker** (FR-036): `status` flips to `unhealthy` when
`consecutive_failures ≥ 5`; `next_recheck_at = NOW() + 60s`.

---

### `zlibrary_quota`

Singleton table tracking Z-Library daily quota (FR-005).

| Column | Type | Constraints |
|--------|------|-------------|
| `date_utc` | DATE | PK (yyyy-mm-dd) |
| `downloads_used` | INTEGER | NOT NULL DEFAULT 0 |
| `downloads_max` | INTEGER | NOT NULL DEFAULT 10 |
| `reset_at_utc` | TIMESTAMP WITH TZ | NOT NULL (next midnight UTC) |

---

### `notifications_log`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUIDv7 | PK |
| `event_type` | TEXT | NOT NULL |
| `source_id` | TEXT | nullable (populated for source-scoped events) |
| `title` | TEXT | NOT NULL |
| `body` | TEXT | NOT NULL |
| `severity` | TEXT | NOT NULL (`info` \| `warning` \| `error`) |
| `metadata` | JSON | NOT NULL |
| `dispatched_at` | TIMESTAMP WITH TZ | NOT NULL |
| `coalesced` | BOOLEAN | NOT NULL DEFAULT FALSE (per FR-031a) |
| `dispatch_status` | TEXT | NOT NULL (`sent` \| `failed` \| `suppressed`) |

**Indexes**: `INDEX(dispatched_at DESC)`; `INDEX(event_type, source_id,
dispatched_at DESC)` for flap-suppression lookup.

**Retention**: 30 days, aligned with downloads history.

---

### `apprise_urls`

Operator-managed list of Apprise destinations (not secrets in the strict
sense, but encrypted at rest via `cryptography.fernet` keyed by a config-
derived master key).

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUIDv7 | PK |
| `label` | TEXT | NOT NULL |
| `url_encrypted` | BLOB | NOT NULL |
| `subscribed_events` | JSON | NOT NULL (list of `NotificationEvent`) |
| `enabled` | BOOLEAN | NOT NULL DEFAULT TRUE |
| `created_at` | TIMESTAMP WITH TZ | NOT NULL DEFAULT NOW |

---

### `webhook_config` (singleton)

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PK CHECK (`id = 1`) |
| `url` | TEXT | nullable |
| `headers` | JSON | NOT NULL DEFAULT `{}` |
| `body_template` | TEXT | NOT NULL (Jinja2) |
| `subscribed_events` | JSON | NOT NULL |
| `enabled` | BOOLEAN | NOT NULL DEFAULT FALSE |

---

### `search_cache`

Orchestrator result cache (FR-013, 15-minute TTL).

| Column | Type | Constraints |
|--------|------|-------------|
| `cache_key` | TEXT | PK (`sha256(normalized_query \| profile_slug \| filters_hash)`) |
| `profile_id` | UUIDv7 | NOT NULL |
| `results` | JSON | NOT NULL (serialized `list[SearchResult]`) |
| `stored_at` | TIMESTAMP WITH TZ | NOT NULL |
| `expires_at` | TIMESTAMP WITH TZ | NOT NULL |

**Indexes**: `INDEX(expires_at)` for sweep.

---

## Derived / transient objects (not persisted)

These are in-memory dataclasses that flow through the application; they are
NOT tables but are documented here for contract clarity.

### `SearchResult`

```python
@dataclass(frozen=True)
class SearchResult:
    external_id: str
    title: str
    author: str | None
    year: int | None
    format: str                 # e.g. "epub", "pdf", "mp3"
    language: str | None        # ISO 639-1
    size_bytes: int | None
    quality_score: float        # 0–∞; see R-14
    source_id: str
    media_type: MediaType
    metadata: dict[str, Any]    # adapter-specific extras (covers, ISBN, etc.)
```

### `DownloadInfo`

```python
@dataclass(frozen=True)
class DownloadInfo:
    download_url: str
    size_bytes: int | None       # from HEAD or source metadata
    content_type: str | None
    filename_hint: str
    extra_headers: dict[str, str]  # cookies, auth, UA overrides
```

### `HealthStatus` (adapter return value)

```python
@dataclass(frozen=True)
class HealthStatus:
    status: AdapterHealth
    reason: UnhealthyReason | None
    message: str | None          # human-readable, must be redaction-safe
    checked_at: datetime
```

### `QuotaStatus`

```python
@dataclass(frozen=True)
class QuotaStatus:
    used: int
    limit: int
    resets_at: datetime
```

### `ConfigSchema` (returned by `adapter.get_config_schema()`)

```python
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
```

---

## Relationships (ER overview)

```text
profiles ─┬─ 1:N ─→ downloads
          └─ 1:N (logical) ─→ search_cache

downloads ─ 1:1 ─ torrents
torrents ─ 1:N ─ tracker_peers (info_hash)

adapter_health ─ 1:N (logical) ─ notifications_log (source_id)

bypass_sessions: standalone, keyed by domain
zlibrary_quota: singleton per date_utc
settings: standalone KV
apprise_urls, webhook_config: standalone
```

No foreign keys cross the `vendor/` boundary — vendored Shelfmark code is
stateless with respect to our database.
