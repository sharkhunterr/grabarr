"""Bypass service — switchable external / internal / auto dispatcher.

Per spec FR-009 + Constitution Article VIII the actual bypass logic
lives in the vendored ``bypass/{external,internal}_bypasser.py``
modules. This service layer owns:

  - mode selection (from settings → env → default 'external'),
  - FlareSolverr reachability probe for the health monitor,
  - session-cache read/write via :mod:`grabarr.bypass.cache`,
  - graceful fallback from 'auto' mode: try external first, fall
    back to internal on connection failure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from grabarr.adapters.base import AdapterBypassError
from grabarr.core.enums import BypassMode
from grabarr.core.logging import setup_logger

_log = setup_logger(__name__)


@dataclass(frozen=True)
class BypassResult:
    """What a successful bypass returns (for the adapter to reuse)."""

    cf_clearance: str
    user_agent: str
    mode_used: BypassMode


def resolve_mode() -> BypassMode:
    """Return the configured bypass mode (env → default)."""
    raw = os.environ.get("GRABARR_BYPASS_MODE", BypassMode.EXTERNAL.value)
    try:
        return BypassMode(raw)
    except ValueError:
        return BypassMode.EXTERNAL


async def probe_flaresolverr() -> bool:
    """Cheap health check for the FlareSolverr sidecar."""
    url = os.environ.get(
        "GRABARR_SHELFMARK_EXT_BYPASSER_URL", "http://flaresolverr:8191/v1"
    )
    probe = url.rstrip("/").rsplit("/", 1)[0]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(probe + "/")
        return r.status_code < 500
    except httpx.HTTPError:
        return False


async def solve(url: str, session_timeout: int = 60) -> BypassResult:
    """Run the configured bypass flow against ``url``.

    For ``external``, delegates to Shelfmark's vendored FlareSolverr
    client. For ``internal`` → SeleniumBase (requires the optional
    extra). For ``auto``, tries external first then falls back.

    Raises :class:`AdapterBypassError` on total failure.
    """
    mode = resolve_mode()
    order: list[BypassMode]
    if mode == BypassMode.AUTO:
        order = [BypassMode.EXTERNAL, BypassMode.INTERNAL]
    else:
        order = [mode]

    last_exc: Exception | None = None
    for attempt in order:
        try:
            if attempt == BypassMode.EXTERNAL:
                return await _solve_external(url, session_timeout)
            if attempt == BypassMode.INTERNAL:
                return await _solve_internal(url, session_timeout)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            _log.warning("bypass mode %s failed: %s", attempt.value, exc)
            continue
    raise AdapterBypassError(
        f"all bypass modes failed (last error: {last_exc})"
    ) from last_exc


async def _solve_external(url: str, timeout: int) -> BypassResult:
    """Use the vendored FlareSolverr client."""
    import asyncio

    from grabarr.vendor.shelfmark.bypass import external_bypasser

    fn = getattr(external_bypasser, "get_bypassed_page", None)
    if not callable(fn):
        raise AdapterBypassError("vendored external_bypasser exposes no get_bypassed_page")

    try:
        result = await asyncio.to_thread(fn, url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        raise AdapterBypassError(f"external bypasser raised: {exc}") from exc

    # The vendored function returns HTML + possibly cookies / user agent.
    if not result:
        raise AdapterBypassError("external bypasser returned empty result")

    # Shelfmark's API varies by version; accept dict or tuple.
    cookie = ""
    ua = ""
    if isinstance(result, dict):
        cookie = result.get("cf_clearance", "") or result.get("cookie", "")
        ua = result.get("user_agent", "")
    elif isinstance(result, tuple) and len(result) >= 2:
        cookie = result[1] if isinstance(result[1], str) else ""
        ua = result[2] if len(result) > 2 and isinstance(result[2], str) else ""

    return BypassResult(cf_clearance=cookie, user_agent=ua, mode_used=BypassMode.EXTERNAL)


async def _solve_internal(url: str, timeout: int) -> BypassResult:
    """Use the vendored SeleniumBase bypasser (optional extra)."""
    try:
        from grabarr.vendor.shelfmark.bypass import internal_bypasser
    except ImportError as exc:
        raise AdapterBypassError(
            "internal bypasser requires the 'internal-bypasser' optional "
            "extra: `uv sync --extra internal-bypasser`"
        ) from exc

    import asyncio

    fn = getattr(internal_bypasser, "get_bypassed_page", None)
    if not callable(fn):
        raise AdapterBypassError("vendored internal_bypasser exposes no get_bypassed_page")
    try:
        result = await asyncio.to_thread(fn, url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        raise AdapterBypassError(f"internal bypasser raised: {exc}") from exc

    if isinstance(result, dict):
        cookie = result.get("cf_clearance", "")
        ua = result.get("user_agent", "")
    else:
        cookie = ""
        ua = ""
    return BypassResult(cf_clearance=cookie, user_agent=ua, mode_used=BypassMode.INTERNAL)


# --------------------------------------------------------------------------
# fetch_html — let any adapter pull a CF/Turnstile-protected page
# --------------------------------------------------------------------------


async def fetch_html(
    url: str,
    *,
    prefer_internal: bool = False,
    timeout: int = 60,
) -> str:
    """Return the rendered HTML of ``url`` after running through the bypass.

    Vendored ``internal_bypasser.get(url)`` (SeleniumBase cdp_driver) and
    ``external_bypasser.get_bypassed_page(url)`` (FlareSolverr) both
    return the post-challenge HTML as a plain string. This wrapper picks
    one based on the configured bypass.mode, falling back across modes
    when ``mode == auto``.

    Adapters that scrape Cloudflare-protected pages (RomsFun,
    hShop's Turnstile-gated download page, etc.) call this to acquire
    the rendered HTML, then parse it with BeautifulSoup as if no
    challenge was present.

    ``prefer_internal=True`` flips the auto-mode order to (internal,
    external) — useful for sites with Cloudflare Turnstile, which
    FlareSolverr does not solve but a real Chromium often does.

    Raises ``AdapterBypassError`` if every configured mode fails.
    """
    import asyncio

    mode = resolve_mode()
    order: list[BypassMode]
    if mode == BypassMode.AUTO:
        order = (
            [BypassMode.INTERNAL, BypassMode.EXTERNAL]
            if prefer_internal
            else [BypassMode.EXTERNAL, BypassMode.INTERNAL]
        )
    else:
        order = [mode]

    last_exc: Exception | None = None
    for attempt in order:
        try:
            if attempt == BypassMode.EXTERNAL:
                from grabarr.vendor.shelfmark.bypass import external_bypasser

                fn = external_bypasser.get_bypassed_page
                html = await asyncio.to_thread(fn, url)
            elif attempt == BypassMode.INTERNAL:
                try:
                    from grabarr.vendor.shelfmark.bypass import internal_bypasser
                except ImportError as exc:
                    raise AdapterBypassError(
                        "internal bypasser requires the 'internal-bypasser' "
                        "extra: `uv sync --extra internal-bypasser`"
                    ) from exc
                html = await asyncio.to_thread(internal_bypasser.get, url)
            else:
                continue
            if html:
                _log.info("bypass.fetch_html: %s mode succeeded for %s", attempt.value, url)
                return html
            _log.info("bypass.fetch_html: %s mode returned empty for %s", attempt.value, url)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            _log.warning(
                "bypass.fetch_html: %s mode raised for %s: %s", attempt.value, url, exc
            )
            continue

    raise AdapterBypassError(
        f"fetch_html failed for {url} (last error: {last_exc})"
    ) from last_exc
