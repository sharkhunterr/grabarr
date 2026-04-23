# Grabarr

The missing bridge between shadow libraries and the *arr ecosystem.

Grabarr is a multi-source media indexer and download bridge that exposes
Anna's Archive, LibGen, Z-Library, and Internet Archive as standard Torznab
indexers consumable by Prowlarr and the *arr apps (Bookshelf, Readarr,
Mylar3, etc.). It downloads HTTP files and generates seedable `.torrent`
files on the fly so that any standard BitTorrent client (Deluge,
qBittorrent, Transmission, rTorrent) can consume them transparently.

## Status

**v1.0 — in development.** See `specs/001-grabarr-core-platform/` for the
full specification, plan, data model, contracts, quickstart, and
177-task implementation breakdown.

## Quick start

See `specs/001-grabarr-core-platform/quickstart.md` for end-to-end setup
(operator, developer, and QA paths).

## Licensing

- Grabarr's own code: **GPL-3.0-or-later**.
- Vendored Shelfmark modules (`grabarr/vendor/shelfmark/`): **MIT**, see
  `grabarr/vendor/shelfmark/ATTRIBUTION.md`.

## Non-goals

Grabarr is not a download manager for end users, not a library manager,
not a metadata provider, and does not redistribute content. See the
constitution (`.specify/memory/constitution.md`) §"Scope Boundaries".
