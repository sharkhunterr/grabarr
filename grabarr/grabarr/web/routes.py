"""HTML routes for the admin UI.

For v1.0 MVP the surface is: Dashboard + Profiles list. The richer
Profiles edit/test, Sources, Settings, Downloads history, Notifications,
and Stats pages land in US3 / US4 / Polish phases.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from grabarr import __version__
from grabarr.core.registry import get_registered_adapters
from grabarr.profiles.service import list_profiles

router = APIRouter(tags=["web"])

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
# Python 3.14 + jinja2's template-cache key includes the globals dict,
# which is unhashable. Disable the cache so get_template bypasses it.
templates.env.cache = None


def mount_static(app: object) -> None:
    """Attach ``/static`` to the given FastAPI app."""
    from fastapi import FastAPI  # lazy

    if isinstance(app, FastAPI):
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Minimal dashboard (MVP): show version, adapters, profile count."""
    profiles = await list_profiles()
    adapters = get_registered_adapters()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "version": __version__,
            "profile_count": len(profiles),
            "adapter_count": len(adapters),
            "adapters": adapters,
        },
    )


@router.get("/profiles", response_class=HTMLResponse)
async def profiles_list(request: Request) -> HTMLResponse:
    """List every profile with its Torznab URL + Copy Prowlarr Config action."""
    profiles = await list_profiles()
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    return templates.TemplateResponse(
        request,
        "profiles/list.html",
        {
            "profiles": profiles,
            "base_url": base_url,
        },
    )


@router.get("/profiles/new", response_class=HTMLResponse)
async def profile_new(request: Request) -> HTMLResponse:
    """Empty profile-edit form for creating a new profile."""
    from grabarr.core.enums import MediaType

    # Build a placeholder object that behaves like a Profile for the template.
    blank = type(
        "_BlankProfile",
        (),
        {
            "slug": "",
            "name": "",
            "description": "",
            "media_type": MediaType.EBOOK.value,
            "mode": "first_match",
            "newznab_categories": [7020],
            "sources": [],
            "filters": {"languages": [], "preferred_formats": []},
            "download_mode_override": None,
            "torrent_mode_override": None,
            "enabled": True,
            "is_default": False,
        },
    )()
    return templates.TemplateResponse(
        request,
        "profiles/edit.html",
        {
            "profile": blank,
            "is_new": True,
            "adapters": get_registered_adapters(),
            "media_types": [m.value for m in MediaType],
        },
    )


@router.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request) -> HTMLResponse:
    """Adapter list + health + config schema."""
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=request.app),
        base_url=str(request.base_url).rstrip("/"),
    ) as client:
        r = await client.get("/api/sources")
    data = r.json()
    return templates.TemplateResponse(
        request, "sources.html", {"items": data.get("items", [])}
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    from grabarr.core.settings_service import get_all

    return templates.TemplateResponse(
        request, "settings.html", {"settings": await get_all()}
    )


@router.get("/downloads", response_class=HTMLResponse)
async def downloads_page(
    request: Request,
) -> HTMLResponse:
    import math

    import httpx

    qp = dict(request.query_params)
    page = max(int(qp.get("page", 1)), 1)
    size = int(qp.get("size", 50))

    # Serialise through our own /api/downloads to share the filter logic.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=request.app),
        base_url=str(request.base_url).rstrip("/"),
    ) as client:
        params = {k: qp.get(k, "") for k in ("status", "source", "profile", "q")}
        params["page"] = str(page)
        params["size"] = str(size)
        r = await client.get("/api/downloads", params=params)
    data = r.json()
    pages = max(math.ceil((data.get("total", 0) or 1) / size), 1)

    # Rebuild query string for pagination links.
    keep = {k: v for k, v in qp.items() if k != "page" and v}
    query_suffix = ("&" + "&".join(f"{k}={v}" for k, v in keep.items())) if keep else ""

    return templates.TemplateResponse(
        request,
        "downloads.html",
        {
            "items": data.get("items", []),
            "total": data.get("total", 0),
            "page": page,
            "pages": pages,
            "query_suffix": query_suffix,
            "filter_status": qp.get("status", ""),
            "filter_source": qp.get("source", ""),
            "filter_profile": qp.get("profile", ""),
            "filter_q": qp.get("q", ""),
        },
    )


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request) -> HTMLResponse:
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=request.app),
        base_url=str(request.base_url).rstrip("/"),
    ) as client:
        overview = (await client.get("/api/stats/overview")).json()
        tops = (await client.get("/api/stats/top-queries?limit=10")).json()
    return templates.TemplateResponse(
        request,
        "stats.html",
        {"overview": overview, "top_titles": tops.get("items", [])},
    )


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request) -> HTMLResponse:
    """Apprise URL list + recent dispatch log."""
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=request.app),
        base_url=str(request.base_url).rstrip("/"),
    ) as client:
        urls = (await client.get("/api/notifications/apprise")).json()
        log = (await client.get("/api/notifications/log?size=20")).json()
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {"urls": urls.get("items", []), "log_items": log.get("items", [])},
    )


@router.get("/profiles/{slug}/prowlarr-setup", response_class=HTMLResponse)
async def profile_prowlarr_setup(slug: str, request: Request) -> HTMLResponse:
    """Per-profile Prowlarr-setup page — all fields + key in one place."""
    from fastapi import HTTPException

    from grabarr.profiles.service import (
        ProfileNotFound,
        get_or_mint_api_key,
        get_profile_by_slug,
    )

    try:
        profile = await get_profile_by_slug(slug)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail=f"profile '{slug}' not found") from None
    # get_or_mint reads the stored plaintext; NO rotation on visit.
    api_key = await get_or_mint_api_key(slug)
    base_url = f"{request.url.scheme}://{request.url.netloc}/torznab/{slug}"
    return templates.TemplateResponse(
        request,
        "profiles/prowlarr_setup.html",
        {
            "profile": profile,
            "api_key": api_key,
            "base_url": base_url,
            "name": f"Grabarr — {profile.name}",
        },
    )


@router.get("/profiles/{slug}/edit", response_class=HTMLResponse)
async def profile_edit(slug: str, request: Request) -> HTMLResponse:
    """Edit form for an existing profile."""
    from grabarr.core.enums import MediaType
    from grabarr.profiles.service import ProfileNotFound, get_profile_by_slug

    try:
        profile = await get_profile_by_slug(slug)
    except ProfileNotFound:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"profile '{slug}' not found") from None
    return templates.TemplateResponse(
        request,
        "profiles/edit.html",
        {
            "profile": profile,
            "is_new": False,
            "adapters": get_registered_adapters(),
            "media_types": [m.value for m in MediaType],
        },
    )
