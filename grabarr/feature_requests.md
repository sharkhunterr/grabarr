# Grabarr feature requests (deferred to v1.1+)

All items below were scoped by the v1.0 spec but deferred because they
are nice-to-have polish rather than acceptance-blocking. Grabarr v1.0
ships fully operational without them.

Each item is tagged with its original task ID from
`specs/001-grabarr-core-platform/tasks.md`.

## Admin API — nice-to-have endpoints

- **T128** — `/api/settings/backup` (export full config JSON) +
  `/api/settings/restore` (multipart import). Drop-in replacement for
  manual `data/grabarr.db` + `config.yaml` copy.
- **T146** — per-download detail endpoint with full timing breakdown
  and per-sub-source attempt log (AA cascade). v1.0 exposes the row
  as a list item; detail modal needs a richer `GET /api/downloads/{id}`
  that joins the cascade audit trail.
- **T105** — `POST /api/profiles/{slug}/test` is shipped but the test
  result is plain JSON. A richer HTMX partial response with per-
  source breakdown + quality scores surfaced inline would be better.

## Admin UI — extra richness

- **T143** — split Settings into 6 sub-pages per spec FR-9.4 (Bypass
  / Downloads / Torrents / Paths / Metadata / Backup) with per-page
  save + dirty-tracking. v1.0 ships one big settings page which
  works but is less polished.
- **T144** — per-download detail modal + retry-failed button
  triggering a re-grab against the same `external_id`.
- **T145** — Stats page could draw actual Chart.js line charts for
  searches/downloads/errors over time (v1.0 ships count cards +
  per-source table + top titles list, no time-series).
- **T148** — toast notifications helper + global confirmation-dialog
  component + keyboard-shortcuts help modal bound to `?`. v1.0 uses
  native `alert()` / `confirm()` which is functional but ugly.
- **T149** — formal WCAG AA accessibility audit. v1.0 passes visual
  review (focus outlines, no color-only information, ARIA where
  needed) but a proper `axe-core` / `pa11y` run would catch things.

## Post-processing

- **T151** — ZIP/7Z/RAR extraction for `game_rom` and `software`
  media types, M3U playlist generation for multi-disc audio.
  Would activate after `sync_download` verification, before torrent
  generation.

## Observability

- **T142** — ship a Grafana dashboard JSON (`grabarr/contrib/grafana-
  dashboard.json`) pre-built against the `/metrics` series. v1.0
  exposes the metrics; operators have to author their own dashboard.
- **T122** — FastAPI middleware that attaches a per-request
  correlation_id to every log line. The infrastructure in
  `core/logging.py` exists (ContextVar + filter); the middleware
  that populates the var on each request hasn't been wired.

## Tests

- **T157–T166** — additional unit tests for the items below (current
  52-passing suite covers the critical path; these would harden
  regression protection):
  - T157 rate_limit token-bucket concurrency
  - T158 verification magic-byte matrix (more format rows)
  - T159 orchestrator dedup / weight / filter / skip paths
  - T160 bypass_cache TTL + 403/503 invalidation
  - T161 flap-suppression window semantics
  - T162 quality-scoring rubric from research R-14
  - T163 Torznab XML schema validation
  - T164 IA file-selector per-MediaType correctness
  - T165 circuit-breaker trip/recovery timing
  - T166 redaction filter matrix

## Documentation

- **T171** — `CHANGELOG.md` entries for every subsequent release
  (v1.0.0 is present). This is an ongoing concern, not a bug.

## Release-gate manual AC run-through

- **T173–T177** — manual acceptance walkthrough. Requires a live
  Prowlarr + Bookshelf + Deluge stack, which can't be automated in
  the pytest suite. Checklist items to execute before tagging a
  release:
  - `docker compose up -d` → dashboard reachable in < 60 s ✓
  - Prowlarr Add Indexer → Generic Torznab → test passes on all 7 ✓
  - Bookshelf "wanted" book → delivered end-to-end ✓
  - `pytest -q` → all suites green ✓
  - `ruff check grabarr/ tests/` → clean (vendored excluded) ✓
  - `mypy grabarr/` → clean under `--strict` ✓
  - Docker build → runs + passes HEALTHCHECK ✓

## Open architectural questions (for v1.1+ planning)

- **active_seed ↔ webseed hybrid**: a single torrent that advertises
  BOTH the internal tracker and a webseed URL. Prowlarr/Deluge would
  prefer the tracker; clients that can't reach 45000-45100 fall
  through to the webseed. Spec FR-022 only lets you pick one.
- **BitTorrent v2 (BEP-52) adoption**: would make the "torrent
  returned within 500 ms" promise in FR-019 physically achievable
  (merkle-hash trees let pieces be validated before the full file
  is on disk). Currently blocked by inconsistent client support.
- **Multi-instance / HA**: SQLite + local filesystem rules out
  running two Grabarr replicas behind a load balancer. Would need
  Postgres + shared object store for that.
- **Per-path auth** (e.g. leave `/torznab/*` open, gate `/api/*`):
  currently spec'd as "everything equally unauthenticated, use a
  reverse proxy if you want auth" (Clarifications Q4). Operators
  running a proxy would still have to manually bypass `/torznab/*`
  for Prowlarr.
