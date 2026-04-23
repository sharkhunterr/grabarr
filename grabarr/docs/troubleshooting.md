# Grabarr troubleshooting

## Symptom → most likely cause → fix

### Prowlarr's indexer test fails with "unable to connect"

- `baseUrl` in the Generic Torznab form must be reachable from Prowlarr's
  side of the network. `localhost` or `127.0.0.1` refers to Prowlarr's
  own container when Prowlarr is dockerised; use the Docker network
  hostname or the host's LAN IP instead.

### AA searches time out every time

- Check `docker logs flaresolverr`. If it's down, the AA slow tier is
  CF-blocked.
- In a browser, hit `/healthz` → look at `subsystems.flaresolverr.status`.
  Should be `ok`. If `fail`, restart the FlareSolverr container.
- If FlareSolverr is up but AA specifically is unhealthy, visit
  `/sources` and click *Test Now* on Anna's Archive to get the
  actual failure reason.

### Z-Library returns empty on every query

- No `remix_userid` + `remix_userkey` configured. Grab both from
  your Z-Library account → *Settings* → *Cookies*. Set via
  `config.yaml` or `GRABARR_SOURCES__ZLIBRARY__REMIX_USERID`/
  `GRABARR_SOURCES__ZLIBRARY__REMIX_USERKEY`. Restart Grabarr.
- If the adapter is healthy in `/healthz` but still empty, cookies
  likely expired — visit `/sources`, confirm the health dot is red
  with reason `cookie_expired`, then refresh the cookies.

### `.torrent` downloaded but Deluge won't seed

- If `X-Grabarr-Torrent-Mode: active_seed`, Deluge needs to reach
  Grabarr at one of the listen ports (45000–45100). Verify the
  compose file publishes that range on the host interface.
- If `webseed`, Deluge ignores the tracker and pulls from the
  `url-list`. Make sure the `seed/{token}` endpoint is reachable
  from Deluge's side of the network.

### Disk filling up

- Files under `/downloads/ready/` are purged 24 h after torrent
  generation by default. Drop the retention window in
  `docker-compose.yml` via a future `settings.torrent.
  seed_retention_hours` key (currently hardcoded to 24 in the
  cleanup sweeper).
- The sweeper logs every pass; check `docker logs grabarr | grep
  cleanup` to see what it removed.

### "Profile not found" when Prowlarr tries to test a newly imported indexer

- The JSON blob embeds a one-time API key. If you downloaded the
  blob and a minute later regenerated the key (via *Copy Prowlarr
  Config* again), the old blob is invalid. Re-download and re-paste
  into Prowlarr.

### libtorrent ImportError on `active_seed` grab

- Only affects builds from source or non-standard Python versions.
  On `python:3.12-slim` (the shipped Dockerfile), the binding is
  compiled from apt's `libtorrent-rasterbar-dev` in the builder
  stage. On bleeding-edge Python there may be no wheel — pin to
  3.12 or 3.13 for dev, or use `webseed` mode as a fallback.

### /metrics returns < 50 series

- Some series are lazily created on first increment. Run a handful
  of searches across multiple profiles + sources; the distinct
  `(source, profile, status)` label tuples grow quickly to >50.

### Notifications never fire

- Flap suppression coalesces repeats within a 10-minute window per
  `(source, event_type)`. Check `/notifications` → "Recent
  dispatches" for `coalesced=true` / `status=suppressed` entries.
- Test an Apprise URL directly from the UI using the *Test* button
  next to the entry in the *Notifications* page — that invocation
  bypasses the cooldown.

### Where to look

| What | Where |
|------|-------|
| Adapter health | `GET /healthz` + `/sources` UI |
| Per-adapter status | `GET /api/sources` |
| Dispatch audit | `GET /api/notifications/log` |
| Config currently applied | `docker logs grabarr` (at boot) |
| Disk usage | `du -sh downloads/ready/` |
| libtorrent session state | `{data_dir}/session.state` (binary; don't edit) |
