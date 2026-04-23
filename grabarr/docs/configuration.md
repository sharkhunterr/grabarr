# Grabarr configuration reference

Every configurable knob, with its default, valid range, and override
path. Most values can be set three ways:

1. In `config.yaml` (mounted at `/config/grabarr.yaml` in Docker).
2. As a `GRABARR_*` environment variable.
3. In the admin UI's *Settings* page (when applicable).

Precedence (highest wins): env var > config.yaml > admin UI > built-in default.

## Server (boot-time only)

| Key | Default | Description |
|-----|---------|-------------|
| `server.host` | `0.0.0.0` | Bind address for the HTTP server. |
| `server.port` | `8080` | Bind port. |
| `server.data_dir` | `data` | SQLite DB + libtorrent session state + bypass cache key. |
| `server.downloads_dir` | `downloads` | Staging area for `incoming/` and `ready/` files. |

## Logging

| Key | Default | Valid values |
|-----|---------|--------------|
| `logging.level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `logging.format` | `text` | `text` (human-readable, coloured) or `json` |
| `logging.modules` | `{}` | Per-module level overrides, e.g. `grabarr.adapters.anna_archive: DEBUG` |

Environment override for format: `LOG_FORMAT=json`.

## Source credentials

Credentials NEVER leave the process through logs (Constitution Article XIII).

| Key | Env var | Required for |
|-----|---------|--------------|
| `sources.anna_archive.member_key` | `GRABARR_SOURCES__ANNA_ARCHIVE__MEMBER_KEY` | AA fast-download path |
| `sources.zlibrary.remix_userid` | `GRABARR_SOURCES__ZLIBRARY__REMIX_USERID` | Z-Library adapter |
| `sources.zlibrary.remix_userkey` | `GRABARR_SOURCES__ZLIBRARY__REMIX_USERKEY` | Z-Library adapter |
| `master_secret` | `GRABARR_MASTER_SECRET` | Apprise URL encryption at rest |

## Download modes (FR-017)

| Key | Default | Values |
|-----|---------|--------|
| `GRABARR_DOWNLOAD_MODE` env | `sync` | `sync`, `async_streaming`, `hybrid` |
| Per-profile override | `null` | same |
| `hybrid` threshold | 50 MiB | HEAD-probed `Content-Length` cutoff. |

## Torrent modes (FR-022)

| Key | Default | Values |
|-----|---------|--------|
| `GRABARR_TORRENT_MODE` env | `active_seed` | `active_seed`, `webseed` |
| Per-profile override | `null` | same |
| `GRABARR_TORRENT_LISTEN_PORT_MIN` | `45000` | libtorrent range low (active_seed). |
| `GRABARR_TORRENT_LISTEN_PORT_MAX` | `45100` | libtorrent range high. |

Seed retention defaults to 24 h from torrent generation. Files under
`/downloads/ready/{token}/` are purged by the background sweeper
(FR-039a) when the retention window expires. The 30-day history row
stays for observability.

## Bypass service

| Key | Default | Values |
|-----|---------|--------|
| `GRABARR_BYPASS_MODE` env | `external` | `external`, `internal`, `auto` |
| `GRABARR_SHELFMARK_EXT_BYPASSER_URL` env | `http://flaresolverr:8191/v1` | FlareSolverr sidecar URL |

`internal` requires installing the optional extra:
`uv sync --extra internal-bypasser`.

## Rate limits (per-minute)

All values are per adapter; each has its own token bucket.

| Adapter | search/min | download/min | Daily quota |
|---------|-----------:|-------------:|------------:|
| `anna_archive` | 30 | 30 | — |
| `libgen` | 60 | 60 | — |
| `zlibrary` | 10 | 10 | 10 |
| `internet_archive` | 30 | 30 | — |

## Internet Archive policy

IA asks every API consumer to identify themselves. Set:

- `GRABARR_IA_CONTACT_EMAIL` — inserted into the `User-Agent` header.
- `GRABARR_IA_UA_SUFFIX` (optional) — extra `User-Agent` suffix.

## Notifications

- Apprise URLs: managed through the UI at `/notifications` → *Add*.
  URLs are Fernet-encrypted at rest using the `master_secret` (or a
  generated `{data_dir}/.fernet_key` when unset).
- Generic webhook: singleton config via the UI; body is a Jinja2
  template rendered with `{event, title, body, severity, source_id,
  metadata}`.
- Flap suppression: 10-min cooldown per `(source, event_type)`;
  `quota_exhausted` uses an until-midnight-UTC cooldown.

## Observability

| Endpoint | Purpose |
|----------|---------|
| `/healthz` | Aggregate per-subsystem status + adapters |
| `/metrics` | Prometheus exposition (>50 series under load) |
| `/api/notifications/log?page=1&size=50` | Dispatch audit |

## Seed retention + history

| Setting | Default |
|---------|---------|
| Seed retention window | 24 h |
| Downloads history retention | 30 d |
| Bypass session TTL | 30 min (sliding + 403/503 reactive invalidation) |
| Search cache TTL | 15 min |
| Tracker peer TTL | 30 min |
| Notifications log retention | 30 d |

## Ports you may need to expose

| Port | Purpose | Required for |
|------|---------|--------------|
| 8080 | HTTP (UI + Torznab + `/announce` tracker + `/seed/{token}`) | All modes |
| 45000-45100/tcp+udp | libtorrent listening range | `active_seed` mode only |

FlareSolverr's port (8191) is called only over the internal Docker
network — do NOT publish it on the host.
