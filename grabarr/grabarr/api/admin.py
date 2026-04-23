"""Admin REST surface — minimal v1.0 subset.

The full surface lives in ``specs/001-grabarr-core-platform/contracts/
admin-api.md``. This first pass ships just the endpoints US1 needs:

- ``GET /api/profiles`` — list profiles (no auth per FR-033 clarification).
- ``GET /api/profiles/{slug}`` — detail.
- ``POST /api/profiles/{slug}/regenerate-key`` — mint a fresh API key.
- ``GET /api/prowlarr-config?profile={slug}`` — emit a Generic Torznab
  indexer import blob (spec FR-027).

CRUD/PATCH/DELETE + the other endpoints land with US3 / US4.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from grabarr.core.logging import setup_logger
from grabarr.profiles.models import Profile
from grabarr.profiles.service import (
    ProfileNotFound,
    get_profile_by_slug,
    list_profiles,
    regenerate_api_key,
)

router = APIRouter(prefix="/api", tags=["admin"])
_log = setup_logger(__name__)


def _profile_to_dict(p: Profile, base_url: str) -> dict[str, Any]:
    return {
        "id": p.id,
        "slug": p.slug,
        "name": p.name,
        "description": p.description,
        "media_type": p.media_type,
        "mode": p.mode,
        "newznab_categories": p.newznab_categories,
        "sources": p.sources,
        "filters": p.filters,
        "download_mode_override": p.download_mode_override,
        "torrent_mode_override": p.torrent_mode_override,
        "enabled": p.enabled,
        "is_default": p.is_default,
        "torznab_url": f"{base_url}/torznab/{p.slug}/api",
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


@router.get("/profiles")
async def api_list_profiles(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
) -> dict:
    items = await list_profiles()
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    sliced = items[(page - 1) * size : page * size]
    return {
        "page": page,
        "size": size,
        "total": len(items),
        "items": [_profile_to_dict(p, base_url) for p in sliced],
    }


@router.get("/profiles/{slug}")
async def api_get_profile(slug: str, request: Request) -> dict:
    try:
        profile = await get_profile_by_slug(slug)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail=f"profile '{slug}' not found") from None
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    return _profile_to_dict(profile, base_url)


@router.post("/profiles/{slug}/regenerate-key")
async def api_regenerate_key(slug: str) -> dict:
    try:
        plaintext = await regenerate_api_key(slug)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail=f"profile '{slug}' not found") from None
    return {"api_key": plaintext}


@router.get("/prowlarr-config")
async def api_prowlarr_config(
    request: Request,
    profile: str = Query(..., description="Profile slug"),
) -> JSONResponse:
    """Return the Prowlarr Generic Torznab import JSON blob (spec FR-027).

    Fresh API key is minted for every call — the Copy-Config flow is
    the authoritative "give me a new key" path. The key is shown ONCE
    in the JSON ``fields[apiKey].value``; subsequent GETs return a new
    key and invalidate the previous one.
    """
    try:
        prof = await get_profile_by_slug(profile)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail=f"profile '{profile}' not found") from None

    plaintext = await regenerate_api_key(profile)
    host = f"{request.url.scheme}://{request.url.netloc}"

    blob = {
        "enable": True,
        "redirect": False,
        "supportsRss": True,
        "supportsSearch": True,
        "supportsRedirect": False,
        "supportsPagination": True,
        "name": f"Grabarr — {prof.name}",
        "fields": [
            {"order": 0, "name": "baseUrl", "label": "URL",
             "value": f"{host}/torznab/{prof.slug}/"},
            {"order": 1, "name": "apiPath", "label": "API Path", "value": "/api"},
            {"order": 2, "name": "apiKey", "label": "API Key",
             "value": plaintext, "privacy": "apiKey"},
            {"order": 3, "name": "categories", "label": "Categories",
             "value": prof.newznab_categories, "type": "select"},
            {"order": 4, "name": "minimumSeeders", "label": "Minimum Seeders",
             "value": 1},
        ],
        "implementationName": "Torznab",
        "implementation": "Torznab",
        "configContract": "TorznabSettings",
        "infoLink": f"{host}/",
        "tags": ["grabarr", prof.slug],
        "protocol": "torrent",
        "privacy": "public",
        "priority": 25,
        "downloadClientId": 0,
    }
    return JSONResponse(
        content=blob,
        headers={
            "Content-Disposition": (
                f'attachment; filename="grabarr-{prof.slug}.json"'
            ),
        },
    )
