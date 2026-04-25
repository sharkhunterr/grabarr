# Feature 003 — ROM extras behind CF / JS download flows

**Status**: spec only — no new adapters shipped on branch `rom-bypass-extras`.

## Goal of the branch

Tackle the second wave of ROM sources that feature 002 deferred:
hShop, RomsFun, CDRomance, MyAbandonware. The bypass infrastructure
gets a new helper (`bypass.service.fetch_html`) that any non-Shelfmark
adapter can call to render a Cloudflare-protected page through the
existing FlareSolverr / SeleniumBase pipeline. Beyond that, **none of
the four candidate adapters made it past triage** — see findings below.

## What landed

### `bypass.service.fetch_html(url, *, prefer_internal=False, timeout=60) -> str`

A thin facade over the vendored Shelfmark bypassers that returns the
full rendered HTML of a CF-protected URL (instead of just the
clearance cookie). Any adapter can call this from its `search()` or
`get_download_info()` and parse the result with BeautifulSoup as if
no challenge had been present.

Auto-mode tries external (FlareSolverr) first; `prefer_internal=True`
flips the order, useful for sites with Cloudflare Turnstile that
FlareSolverr does not solve but a real Chromium often does.

This unblocks any future adapter that needs CF bypass without baking
the bypass logic into each scraper.

## What did not land — and why

Each site was probed live through the running grabarr Docker container
(`internal_bypasser.get(<url>)`) on 2026-04-25. Every one of them is
"search-fetchable but download-blocked".

### hShop (hshop.erista.me) — Cloudflare Turnstile on download page

- Search HTML: ✅ `/search/results?q=<q>` returns standard `<a class="list-entry">` rows.
- Title detail page (`/t/<id>`): renders metadata fine **but the download box is gated by Cloudflare Turnstile** (`<div class="cf-turnstile" data-sitekey="0x4AAAAAACEl-dv5l_skyfqI">`). The internal bypasser successfully reaches the page but **the Turnstile widget remains unresolved** in the bypass output.
- Turnstile in the "managed" mode often passes for real browsers, but the SeleniumBase cdp_driver running inside Xvfb does NOT pass it consistently (intentional anti-automation by Cloudflare). Running this would need a paid Turnstile-solving service (CapMonster, 2captcha) plugged in as an opt-in extra.

### RomsFun (romsfun.com) — JS-driven download with anti-bot nonce

- Search via `?s=<q>`: ✅ works through internal bypasser. URL **must drop the `www.` subdomain** (`www.romsfun.com` returns a fake "website has been stopped" page; `romsfun.com` returns the real catalog).
- Result list parsed: each result is `<a href="https://romsfun.com/roms/<console>/<slug>.html" class="block w-full h-full">` wrapping `<img alt="Title">`.
- Per-game page exposes ONE `<a href="/download/<slug>-<id>">` button.
- The `/download/<slug>-<id>` page does NOT contain a direct file URL in the HTML. It uses a WordPress AJAX endpoint (`/wp-admin/admin-ajax.php`) gated by a nonce, plus a per-IP daily download limit (FAQ link visible). Reverse-engineering the action name + nonce flow + countdown is moderate work and brittle (any plugin update breaks it).

### CDRomance (cdromance.org) — same pattern as RomsFun

- Search via `?s=<q>`: ✅ HTML returned (123 KB), result anchors point at `https://cdromance.org/<console-slug>/<game-slug>/`.
- Per-game detail page (e.g. `/gamecube/mario-party-4-usa/`): no direct file URL in static HTML. The "Download Now" button is rendered by JS at runtime, the URL likely fetched via AJAX after click.

### MyAbandonware (myabandonware.com) — same pattern again

- Search at `/search/q/<query>`: ✅ 38 result rows, anchors `<a href="/game/<slug>">`.
- Per-game page: download button links to `/download/<id>-<slug>`.
- The `/download/` page does NOT expose the direct file URL in static HTML — JS-driven extraction.

## Why a fetch isn't enough

`fetch_html()` returns the HTML rendered by Chromium AFTER the CF
challenge resolves. That's enough to scrape search results and
detail-page metadata. **It is NOT enough to follow a click-triggered
download flow** because:

1. The download URL is generated server-side at click time, often
   bound to a one-shot nonce or a session cookie set during the
   click handler.
2. Some sites add a synthetic countdown timer that has to fire in a
   real browser context before the URL is exposed.
3. Daily / per-IP download limits would invalidate cached URLs anyway.

To support these flows we'd need a **driver-level adapter abstraction**
that boots Chromium, navigates to the detail page, **clicks** the
download button, captures the network request that follows (or the
DOM mutation that exposes the URL), then hands the URL back to
grabarr's HTTP client. The cdp_driver underlying `internal_bypasser`
supports all of this, but exposing it cleanly to grabarr adapters is
a non-trivial refactor — a feature 004, not a tweak to 003.

## Out of scope for this PR

- A `bypass.service.click_and_capture(url, button_selector)` driver
  helper that returns the resolved URL.
- An opt-in Turnstile solver integration (CapMonster / 2captcha) for
  hShop downloads.
- Reverse-engineering each site's WordPress AJAX action + nonce
  pattern (brittle, breaks on plugin updates).

## Recommendation

Ship `bypass.service.fetch_html()` so future work can land cheaply,
keep the four sites in the deferred list of feature 002's spec, and
defer the click-driver pipeline to a dedicated PR if/when it's worth
the maintenance burden.

## Update — branch `rom-click-driver` follow-up (2026-04-25)

A second pass landed `bypass.click_driver.click_and_capture(url, *,
button_text, button_selector, wait_for_url_pattern, timeout)` — a real
Chromium driven via the vendored SeleniumBase ``cdp_driver``, listening
on the CDP ``Browser.downloadWillBegin`` event. The intent was to
implement a working RomsFun adapter on top of it.

**RomsFun bottoming-out**: hours of probing showed RomsFun's flow does
NOT actually need a click handler — every URL is in static HTML, in
3 hops:

1. ``/?s=<q>``                       → search results (anchors to detail).
2. ``/roms/<console>/<slug>.html``  → exposes ``/download/<slug>-<id>``.
3. ``/download/<slug>-<id>``        → exposes ``/download/<slug>-<id>/<n>``.
4. ``/download/<slug>-<id>/<n>``    → contains
   ``<a id="download-link" href="https://sto.romsfast.com/...?token=…">``.

The CDN-signed URL (``sto.romsfast.com``) is right there in the HTML.
The implementation extracted it correctly. **But the actual file fetch
returns 403** with body "Sorry, your request is invalid" — every
combination of (User-Agent, Referer, Accept-* sec-fetch headers) fails.
Even the same token fetched twice in a row from a fresh bypass session
doesn't work for httpx. The token is presumably tied to:

- An HTTP-only session cookie set by the per-file landing page that we
  can't extract (cookies aren't in the bypasser's exposed cookie jar).
- A short IP-validity window the CDN tracks server-side.
- A WebGL/canvas browser fingerprint Cloudflare sometimes layers in.

To actually download from RomsFun we'd need to drive the **bytes** of
the file inside the same Chromium session — i.e. let the browser do
``GET signed-url`` itself, capturing the file from its download
folder. The cdp_driver supports this (``Tab.set_download_path()`` +
``Tab.download_file()``), but it's a different design from the
current grabarr download manager (which expects an HTTP URL it can
fetch with httpx). Wiring this is a bigger refactor than expected.

The **click_and_capture** infrastructure remains in the codebase as
a generic helper for any future site whose URL extraction genuinely
needs JS click execution (hShop's Turnstile-gated download box, for
example, *might* benefit if Turnstile starts auto-passing under
SeleniumBase). The unused RomsFun adapter was reverted.

**Net result of the branch**: shipping the `click_and_capture` helper
+ the `prefer_internal=True` honoring in `fetch_html`. No new working
adapters. RomsFun, hShop, CDRomance, MyAbandonware all need
browser-driven byte downloads — a feature 004 if it's worth it.
