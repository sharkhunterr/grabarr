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
