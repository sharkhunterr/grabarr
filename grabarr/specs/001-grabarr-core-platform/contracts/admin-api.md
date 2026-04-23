# Admin API Contract

**Scope**: Every route under `/api/*`. Unauthenticated from Grabarr's side
(FR-033 + clarification Q4). All responses are JSON. All errors use the
standard problem-details shape below.

## Error shape

```json
{
  "type": "https://grabarr.local/errors/<slug>",
  "title": "Short summary",
  "status": 400,
  "detail": "Human-readable explanation.",
  "errors": [
    { "field": "sources[0].weight", "message": "weight must be >= 0.1" }
  ]
}
```

`errors` is omitted unless the error is a validation failure.

---

## Profiles

### `GET /api/profiles?page={n}&size={k}`

List profiles with pagination (default `size=50`, max `100`).

```json
{
  "page": 1,
  "size": 50,
  "total": 7,
  "items": [
    {
      "id": "018f7b40-...",
      "slug": "ebooks_general",
      "name": "Ebooks General",
      "description": "AA + LibGen + IA + Z-Lib, first-match.",
      "media_type": "ebook",
      "mode": "first_match",
      "newznab_categories": [7020],
      "sources": [
        {"source_id": "anna_archive", "weight": 1.2, "timeout_seconds": 60,
         "enabled": true, "skip_if_member_required": false},
        {"source_id": "libgen",        "weight": 1.0, "timeout_seconds": 45,
         "enabled": true, "skip_if_member_required": false},
        {"source_id": "internet_archive", "weight": 0.9, "timeout_seconds": 30,
         "enabled": true, "skip_if_member_required": false},
        {"source_id": "zlibrary",      "weight": 0.7, "timeout_seconds": 45,
         "enabled": true, "skip_if_member_required": true}
      ],
      "filters": {
        "languages": ["en"],
        "preferred_formats": ["epub", "mobi", "pdf"],
        "min_year": null, "max_year": null,
        "min_size_mb": null, "max_size_mb": null,
        "require_isbn": false,
        "extra_query_terms": ""
      },
      "download_mode_override": null,
      "torrent_mode_override": null,
      "enabled": true,
      "is_default": true,
      "torznab_url": "http://{host}/torznab/ebooks_general/api",
      "created_at": "2026-04-23T09:00:00Z",
      "updated_at": "2026-04-23T09:00:00Z"
    }
  ]
}
```

### `GET /api/profiles/{slug}` → 200 | 404

Same shape as the list element above.

### `POST /api/profiles` → 201 | 400 | 409

Body: same shape as list element (minus `id`, `torznab_url`, timestamps,
`is_default`). Returns the created resource. `409` on slug collision.

### `PATCH /api/profiles/{slug}` → 200 | 400 | 404

Body: partial update (any subset of mutable fields). Returns updated
resource.

### `DELETE /api/profiles/{slug}` → 204 | 403 | 404

`403` if `is_default = true`. Non-default profiles are fully deleted
(download history retains the `profile_id` as orphan; no cascade).

### `POST /api/profiles/{slug}/regenerate-key` → 200 | 404

Response:

```json
{ "api_key": "<plain-text key, shown once>" }
```

The plaintext is returned EXACTLY once; the database stores only its bcrypt
hash. Subsequent calls to `GET /api/profiles/{slug}` MUST NOT leak the
plaintext.

### `POST /api/profiles/{slug}/test` → 200 | 404

Body:

```json
{ "query": "foundation asimov", "limit": 10 }
```

Response (inline test — executes a real search without side effects):

```json
{
  "took_ms": 421,
  "results_per_source": [
    {"source_id": "anna_archive", "count": 7, "took_ms": 312, "error": null},
    {"source_id": "libgen",        "count": 4, "took_ms": 89,  "error": null}
  ],
  "top_results": [
    {
      "title": "Foundation",
      "author": "Isaac Asimov",
      "year": 1951,
      "format": "epub",
      "size_bytes": 524288,
      "quality_score": 164.0,
      "source_id": "anna_archive"
    }
  ]
}
```

### `POST /api/profiles/{slug}/duplicate` → 201 | 404 | 409

Body: `{ "new_slug": "my_ebooks" }`. Creates a copy with `is_default =
false`, a new API key, and all source entries, filters, and overrides
cloned. Returns the new profile.

### `GET /api/prowlarr-config?profile={slug}` → 200 | 404

Returns the Prowlarr "Generic Torznab" import JSON. See
`prowlarr-export.json`.

---

## Sources

### `GET /api/sources` → 200

```json
{
  "items": [
    {
      "id": "anna_archive",
      "display_name": "Anna's Archive",
      "supported_media_types": ["ebook","audiobook","comic","magazine","paper","music"],
      "requires_cf_bypass": true,
      "supports_member_key": true,
      "supports_authentication": false,
      "health": {
        "status": "healthy",
        "reason": null,
        "message": null,
        "checked_at": "2026-04-23T10:12:00Z",
        "consecutive_failures": 0
      },
      "quota": null,
      "enabled": true,
      "config_schema": { "fields": [/* see source-adapter.py */] }
    },
    {
      "id": "zlibrary",
      "...": "...",
      "quota": { "used": 3, "limit": 10, "resets_at": "2026-04-24T00:00:00Z" }
    }
  ]
}
```

### `PATCH /api/sources/{id}` → 200

Body: `{ "enabled": bool }`. Toggle an adapter at runtime (does not touch
config schema).

### `POST /api/sources/{id}/config` → 200 | 400

Body: `{ "<key>": "<value>", ... }` — keys MUST exist in the adapter's
config schema; secret fields are stored via the `fernet` envelope.

### `POST /api/sources/{id}/test` → 200

Triggers an immediate `adapter.health_check()`. Returns the
`HealthStatus`.

---

## Settings

### `GET /api/settings` → 200

Flat JSON dict of every key in the `settings` table.

```json
{
  "download.mode": "sync",
  "download.hybrid_threshold_mb": 50,
  "torrent.mode": "active_seed",
  "bypass.mode": "external",
  "bypass.flaresolverr_url": "http://flaresolverr:8191/v1",
  "rate_limit.anna_archive.search_per_min": 30,
  "metadata.ia_contact_email": "operator@example.com",
  "notifications.flap_cooldown_minutes": 10
}
```

Secrets are NOT returned (redacted to `"***"`).

### `PATCH /api/settings` → 200 | 400

Body: partial dict of keys to update. Keys MUST be in the allowlist
(validation in service layer).

### `POST /api/settings/backup` → 200

Response: downloadable JSON blob of the full config (including profiles,
apprise URLs with encrypted values, webhook config). Suitable for
`POST /api/settings/restore`.

### `POST /api/settings/restore` → 200 | 400

Multipart: `file=<backup.json>`. Replaces all config atomically inside a
transaction.

---

## Downloads History

### `GET /api/downloads?page={n}&size={k}&status={status}&profile={slug}&source={id}&q={query}` → 200

Paginated history, newest first. All filters optional; all AND-combined.

```json
{
  "page": 1,
  "size": 50,
  "total": 127,
  "items": [
    {
      "id": "018f7b40-...",
      "token": "yeVX...",
      "profile_slug": "ebooks_general",
      "source_id": "anna_archive",
      "title": "The Name of the Wind",
      "author": "Patrick Rothfuss",
      "year": 2007,
      "filename": "the-name-of-the-wind.epub",
      "size_bytes": 1048576,
      "download_mode": "sync",
      "torrent_mode": "active_seed",
      "info_hash": "abcd...",
      "status": "completed",
      "failure_reason": null,
      "timings_ms": {
        "resolve": 412,
        "download": 3802,
        "verify": 55,
        "total": 4269
      },
      "started_at": "2026-04-23T09:01:12Z",
      "completed_at": "2026-04-23T09:01:17Z",
      "file_available": true
    }
  ]
}
```

### `GET /api/downloads/{id}` → 200 | 404

Same shape with additional debug fields (per-sub-source attempts for AA,
magic-byte verification result, post-processing log).

### `POST /api/downloads/{id}/retry` → 202 | 404 | 409

`409` if the row is not in `FAILED`. Creates a new `downloads` row with the
same `external_id`/`source_id` and queues it.

### `DELETE /api/downloads/{id}` → 204 | 404

Removes the row. If the file is still on disk, removes it too.

---

## Notifications

### `GET /api/notifications/apprise` → 200

```json
{
  "items": [
    {
      "id": "018f7b40-...",
      "label": "ops-slack",
      "url_masked": "slack://T***/B***/C***",
      "subscribed_events": ["download_failed", "source_unhealthy"],
      "enabled": true
    }
  ]
}
```

### `POST /api/notifications/apprise` → 201 | 400

Body: `{ "label": str, "url": str, "subscribed_events": [...] }`.

### `PATCH /api/notifications/apprise/{id}` → 200

### `DELETE /api/notifications/apprise/{id}` → 204

### `POST /api/notifications/apprise/{id}/test` → 200 | 502

Sends a synthetic test notification.

### `GET /api/notifications/webhook` → 200

### `PUT /api/notifications/webhook` → 200

Body: `{ url, headers, body_template, subscribed_events, enabled }`.

### `POST /api/notifications/webhook/test` → 200 | 502

### `GET /api/notifications/log?page={n}&size={k}&event={type}` → 200

Paginated notification history.

---

## Stats

### `GET /api/stats/overview` → 200

```json
{
  "searches_total": 1243,
  "downloads_total": 412,
  "downloads_succeeded": 398,
  "downloads_failed": 14,
  "bypass_invocations": 47,
  "active_downloads": 2,
  "active_seeds": 37
}
```

### `GET /api/stats/series?metric={name}&from={ts}&to={ts}&resolution={sec}` → 200

Time-series data for charts. Metrics: `searches`, `downloads`, `errors`.

### `GET /api/stats/top-queries?limit={n}` → 200

### `GET /api/stats/export?format={csv|json}` → 200

---

## Health

### `GET /healthz` → 200 | 503

```json
{
  "status": "ok",
  "version": "1.0.0",
  "checked_at": "2026-04-23T10:12:00Z",
  "subsystems": {
    "database": { "status": "ok" },
    "flaresolverr": { "status": "ok", "url": "http://flaresolverr:8191/v1" },
    "libtorrent_session": { "status": "ok", "seeds": 37 },
    "internal_tracker": { "status": "ok", "port": 8999 },
    "adapters": {
      "anna_archive": { "status": "healthy" },
      "libgen": { "status": "healthy" },
      "zlibrary": { "status": "unhealthy", "reason": "cookie_expired" },
      "internet_archive": { "status": "healthy" }
    }
  }
}
```

Returns `503` when any subsystem (except individual adapters) is failing.
Adapter-level failures do NOT fail the overall health (Grabarr is still
usable if one source is down — FR-036, FR-013).

---

## Metrics

### `GET /metrics` → 200

Standard Prometheus text exposition format. Target: > 50 distinct series
under normal operation (SC-010).
