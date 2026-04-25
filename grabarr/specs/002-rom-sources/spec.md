# Feature 002 — ROM sources

**Status**: in development on branch `rom-add` — 2026-04-25.
**Driver**: extend Grabarr's `MediaType.GAME_ROM` coverage beyond the
single Internet Archive adapter shipped in v1.0. v1.0 only matched ROMs
that happened to be a 1-file IA item; the romsets (no-intro, redump)
were unreachable because IA's `metadata/{id}` returns N files and the
adapter picked any ZIP, not the ZIP whose filename matched the user's
query.

## Sources targeted

| Source | Status this PR | Notes |
|---|---|---|
| **Internet Archive** | ✅ romset enhancement | Filename matching for `GAME_ROM` when item has > 3 candidate files. Threads `query_hint` through the search→download pipeline. |
| **Vimm's Lair** (vimm.net) | ✅ full adapter | Search via `/vault/?p=list&system=<sys>&q=<q>`, download via `dl3.vimm.net` GET with form-supplied `mediaId` + Referer. No CF, no auth. Curated USA/EUR sets. |
| **Edge Emulation** (edgeemu.net) | ✅ full adapter | Search via POST to `/search.php` with `search=<q>&system=<sys>`, download URL embedded in result row (`/download/<system>/<filename>`). No CF, no auth. Wide platform coverage. |
| **hShop** (hshop.erista.me) | ⏸ deferred | Search works (`/search/results?q=<q>` → `/t/<id>` listings), but every title-detail page gates the `.cia` download behind a Cloudflare **Turnstile** captcha (not the standard JS challenge — a real captcha widget). FlareSolverr does not solve Turnstile; SeleniumBase cdp_driver passes Turnstile inconsistently and only when run with a real desktop Chrome under Xvfb. Per the user's "search-only is useless" rule we don't ship a half-broken adapter. Future work: route hShop title pages through `bypass.service` with a Turnstile-aware retry loop, OR integrate a paid solver (CapMonster, 2captcha) as an opt-in optional dependency. |
| **RomsFun** (romsfun.com) | ⏸ deferred | Site sits behind a full Cloudflare interstitial challenge (`cf-mitigated: challenge`, 403 to plain GET). Requires routing every search through the existing FlareSolverr/SeleniumBase pipeline, which is currently scoped to the Shelfmark cascade and would need to be extended. Out of scope for this branch. |
| **CDRomance** (cdromance.org) | ⏸ deferred | WordPress + Elementor site, post permalinks not exposed in plain HTML search-results scrape — likely loaded via REST/AJAX. Site recently migrated `.com` → `.org`. Needs more reverse-engineering. Out of scope for this branch. |
| **Myrient** | ✗ not pursued | Site is dead per user feedback. |

## Architecture changes required

The IA romset enhancement requires the **search query to flow from
`search()` to `get_download_info()`**. Today neither is plumbed:

- `SearchResult.metadata` is preserved through the orchestrator but is
  NOT persisted on `SearchToken` / `Download`.
- `Download` only carries `external_id`; `get_download_info(external_id,
  media_type)` has no other context.

This branch wires the query end-to-end:

1. **Schema**: `query: TEXT NULL` column added to `search_tokens` and
   `downloads` (Alembic migration). NULL on legacy rows.
2. **Models**: `SearchToken.query` + `Download.query`.
3. **Service**: `register_result_token(profile, result, *, query)` —
   new kwarg, persisted. `prepare_and_generate_torrent` reads
   `dl.query` and forwards it.
4. **Contract**: `SourceAdapter.get_download_info(external_id,
   media_type, query_hint: str | None = None)`. Optional, default
   `None`. Existing adapters accept and ignore.
5. **IA adapter**: when `media_type == GAME_ROM` and the item has > 3
   candidate files matching the format ladder, score each filename
   against `query_hint` (token-overlap on case-insensitive word
   boundaries) and pick the highest scorer.

## Adapter implementation notes

### Vimm's Lair (`vimm`)

- **Search URL**: `GET https://vimm.net/vault/?p=list&system=<system>&q=<query>`. The `system` param accepts: `NES`, `SNES`, `N64`, `GB`, `GBC`, `GBA`, `DS`, `GC`, `Wii`, `Genesis`, `MS`, `GG`, `Saturn`, `Dreamcast`, `PS1`, `PS2`, `Arcade`, `2600`, `5200`, `7800`, `Lynx`, `Jaguar`. The full mapping lives in `vimm.py::_VIMM_SYSTEMS`.
- **Result rows** are `<table>` rows; each row's first `<a href="/vault/<id>">` is the title link. Region flags are `<img alt="USA"|"Japan"|"Europe"|…>`. Version is plain text.
- **Detail page** (`/vault/<id>`) embeds a `let media=[…];` JS array with `ID`, `GoodTitle` (base64-encoded filename), `Zipped` (KB), `Version`, `GoodHash`, `GoodMd5`, `GoodSha1`. The download form action is `//dl3.vimm.net/` POST with hidden `mediaId`. JS overrides the method to GET via `submitDL`.
- **Download**: `GET https://dl3.vimm.net/?mediaId=<id>` with `Referer: https://vimm.net/vault/<game_id>`. Returns the binary directly with `Content-Disposition` filename.
- **External ID** = the numeric `/vault/<id>` value.

### Edge Emulation (`edge_emulation`)

- **Search URL**: `POST https://edgeemu.net/search.php` form-encoded `search=<q>&system=all` (or a specific system slug). Returns HTML with `<div class="grid"><div class="item"><details data-name="…"><summary>…</summary><p><a href="/download/<system>/<filename>">download</a> (<span>SIZE, NN DLs</span>)</p><p>system: <span>…</span></p>…</details></div>…</div>`.
- **Direct download** — no detail-page hop needed. The result row carries the full download URL.
- **External ID** = the URL-encoded path component, since the filename is the natural ID and there's no numeric ID exposed.

### Internet Archive — romset enhancement

The adapter already has a per-MediaType file-preference ladder
(`_LADDERS[GAME_ROM] = ZIP > 7z > ROM > ISO`). When the item has many
files of the preferred extension (e.g. `nointro.snes` with 3000+ ZIPs),
the current code picks the first one with the highest format score —
arbitrary among ties, which means the user's "Super Mario World"
search returns *some* SNES ZIP, not Super Mario World.

The fix: when there are > 3 candidate files at the top score AND
`query_hint` is non-empty AND `media_type == GAME_ROM`, re-score by
case-insensitive token overlap between the filename (sans extension)
and the query. Pick the highest scorer.

This does NOT touch the file-preference ladder for any other media
type — books, audiobooks, etc. continue to pick by format alone.
Falling back to the highest-format-score-only path when no token
overlaps preserves correctness for legitimate single-ROM IA items.

## Default profiles

The single `roms_all` profile in v1.0 is replaced by a richer set:

- `roms_all` — aggregates Vimm + Edge + IA in `aggregate_all` mode
- `roms_nintendo` — Vimm + Edge pinned to NES/SNES/N64/GB/GBC/GBA/GC/Wii via `extra_query_terms`
- `roms_arcade` — IA's `internetarcade` collection (kept as-is from v1.0)

## Out of scope (deferred to v1.2+)

- RomsFun adapter (needs CF bypass extension to non-Shelfmark adapters)
- CDRomance adapter (WordPress structure needs reverse engineering)
- Per-system filter on Vimm/Edge profiles (today operator picks via the profile's `extra_query_terms`)
- Turnstile solving for hShop (would unlock the 100k+ 3DS catalogue)
