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

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from grabarr.core.logging import setup_logger
from grabarr.profiles.models import Profile
from grabarr.profiles.orchestrator import test_profile as run_test_profile
from grabarr.profiles.service import (
    ProfileDefaultProtected,
    ProfileNotFound,
    ProfileSlugConflict,
    create_profile,
    delete_profile,
    duplicate_profile,
    get_profile_by_slug,
    list_profiles,
    regenerate_api_key,
    update_profile,
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


@router.post("/profiles")
async def api_create_profile(
    request: Request,
    body: dict[str, Any] = Body(...),
) -> JSONResponse:
    """Create a non-default profile. Returns the new row + one-time API key."""
    for required in ("slug", "name", "media_type"):
        if required not in body:
            raise HTTPException(status_code=400, detail=f"missing field: {required}")
    try:
        profile, plaintext = await create_profile(body)
    except ProfileSlugConflict:
        raise HTTPException(
            status_code=409, detail=f"profile slug '{body['slug']}' already exists"
        ) from None
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    data = _profile_to_dict(profile, base_url)
    data["api_key"] = plaintext
    return JSONResponse(content=data, status_code=201)


@router.patch("/profiles/{slug}")
async def api_update_profile(
    slug: str,
    request: Request,
    body: dict[str, Any] = Body(...),
) -> dict:
    try:
        profile = await update_profile(slug, body)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail=f"profile '{slug}' not found") from None
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    return _profile_to_dict(profile, base_url)


@router.delete("/profiles/{slug}", status_code=204)
async def api_delete_profile(slug: str) -> None:
    try:
        await delete_profile(slug)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail=f"profile '{slug}' not found") from None
    except ProfileDefaultProtected:
        raise HTTPException(
            status_code=403,
            detail=f"profile '{slug}' is a default and cannot be deleted (disable instead)",
        ) from None


@router.post("/profiles/{slug}/duplicate")
async def api_duplicate_profile(
    slug: str,
    request: Request,
    body: dict[str, Any] = Body(...),
) -> JSONResponse:
    new_slug = body.get("new_slug")
    if not new_slug:
        raise HTTPException(status_code=400, detail="missing field: new_slug")
    try:
        profile, plaintext = await duplicate_profile(slug, new_slug)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail=f"profile '{slug}' not found") from None
    except ProfileSlugConflict:
        raise HTTPException(
            status_code=409, detail=f"profile slug '{new_slug}' already exists"
        ) from None
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    data = _profile_to_dict(profile, base_url)
    data["api_key"] = plaintext
    return JSONResponse(content=data, status_code=201)


@router.post("/profiles/{slug}/test")
async def api_test_profile(
    slug: str,
    body: dict[str, Any] = Body(default={}),
) -> dict:
    """Run an inline test search against the profile."""
    query = body.get("query", "").strip()
    limit = int(body.get("limit", 10))
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    try:
        profile = await get_profile_by_slug(slug)
    except ProfileNotFound:
        raise HTTPException(status_code=404, detail=f"profile '{slug}' not found") from None
    return await run_test_profile(profile, query, limit=limit)


# ---- Sources -----------------------------------------------------------


@router.get("/sources")
async def api_list_sources() -> dict:
    """List every registered adapter + its health + config schema."""
    from dataclasses import asdict

    from sqlalchemy import select

    from grabarr.adapters.health_model import AdapterHealthRow
    from grabarr.core.registry import get_registered_adapters
    from grabarr.db.session import session_scope
    from grabarr.profiles.service import get_adapter_instance

    adapters = get_registered_adapters()
    async with session_scope() as session:
        rows = await session.execute(select(AdapterHealthRow))
        health_by_id = {r.adapter_id: r for r in rows.scalars().all()}

    items = []
    for aid, cls in sorted(adapters.items()):
        instance = get_adapter_instance(aid)
        schema = instance.get_config_schema() if instance else None
        quota = None
        if instance is not None:
            try:
                q = await instance.get_quota_status()
                if q is not None:
                    quota = {
                        "used": q.used,
                        "limit": q.limit,
                        "resets_at": q.resets_at.isoformat(),
                    }
            except Exception:  # noqa: BLE001
                quota = None
        h = health_by_id.get(aid)
        items.append(
            {
                "id": aid,
                "display_name": cls.display_name,
                "supported_media_types": sorted(m.value for m in cls.supported_media_types),
                "requires_cf_bypass": cls.requires_cf_bypass,
                "supports_member_key": cls.supports_member_key,
                "supports_authentication": cls.supports_authentication,
                "health": {
                    "status": h.status if h else "unknown",
                    "reason": h.reason if h else None,
                    "last_check_at": h.last_check_at.isoformat() if h and h.last_check_at else None,
                    "consecutive_failures": h.consecutive_failures if h else 0,
                },
                "quota": quota,
                "config_schema": {
                    "fields": [asdict(f) for f in (schema.fields if schema else [])],
                },
            }
        )
    return {"items": items}


@router.post("/sources/{source_id}/test")
async def api_test_source(source_id: str) -> dict:
    """Probe an adapter synchronously and return its new HealthStatus."""
    from grabarr.adapters.health import probe_once
    from grabarr.adapters.health_model import AdapterHealthRow
    from grabarr.db.session import session_scope
    from sqlalchemy import select

    await probe_once(source_id)
    async with session_scope() as session:
        row = await session.execute(
            select(AdapterHealthRow).where(AdapterHealthRow.adapter_id == source_id)
        )
        h = row.scalar_one_or_none()
    if h is None:
        raise HTTPException(status_code=404, detail=f"adapter '{source_id}' not registered")
    return {
        "status": h.status,
        "reason": h.reason,
        "last_check_at": h.last_check_at.isoformat(),
        "consecutive_failures": h.consecutive_failures,
        "last_error_message": h.last_error_message,
    }


# ---- Notifications -----------------------------------------------------


@router.get("/notifications/apprise")
async def api_list_apprise() -> dict:
    from sqlalchemy import select

    from grabarr.db.session import session_scope
    from grabarr.notifications.encryption import decrypt, mask
    from grabarr.notifications.models import AppriseUrl

    async with session_scope() as session:
        rows = await session.execute(select(AppriseUrl))
        items = list(rows.scalars().all())
    out = []
    for row in items:
        try:
            plaintext = decrypt(row.url_encrypted)
        except Exception:  # noqa: BLE001
            plaintext = ""
        out.append(
            {
                "id": row.id,
                "label": row.label,
                "url_masked": mask(plaintext) if plaintext else "***",
                "subscribed_events": row.subscribed_events,
                "enabled": row.enabled,
            }
        )
    return {"items": out}


@router.post("/notifications/apprise", status_code=201)
async def api_create_apprise(body: dict[str, Any] = Body(...)) -> dict:
    from grabarr.db.session import session_scope
    from grabarr.notifications.encryption import encrypt
    from grabarr.notifications.models import AppriseUrl

    label = body.get("label")
    url = body.get("url")
    subscribed = body.get("subscribed_events") or []
    if not label or not url or not isinstance(subscribed, list):
        raise HTTPException(status_code=400, detail="label, url, subscribed_events required")
    async with session_scope() as session:
        obj = AppriseUrl(
            label=label,
            url_encrypted=encrypt(url),
            subscribed_events=subscribed,
            enabled=bool(body.get("enabled", True)),
        )
        session.add(obj)
        await session.flush()
        return {"id": obj.id, "label": obj.label}


@router.delete("/notifications/apprise/{url_id}", status_code=204)
async def api_delete_apprise(url_id: str) -> None:
    from sqlalchemy import select

    from grabarr.db.session import session_scope
    from grabarr.notifications.models import AppriseUrl

    async with session_scope() as session:
        row = await session.execute(select(AppriseUrl).where(AppriseUrl.id == url_id))
        obj = row.scalar_one_or_none()
        if obj is None:
            raise HTTPException(status_code=404, detail="not found")
        await session.delete(obj)


@router.post("/notifications/apprise/{url_id}/test")
async def api_test_apprise(url_id: str) -> dict:
    from grabarr.core.enums import NotificationEvent, NotificationSeverity
    from grabarr.notifications.dispatcher import NotificationPayload, dispatch

    await dispatch(
        NotificationPayload(
            event=NotificationEvent.SOURCE_RECOVERED,  # benign test event
            title="Grabarr test notification",
            body=f"Test dispatch from Apprise URL {url_id}.",
            severity=NotificationSeverity.INFO,
        ),
        cooldown_minutes=0,
    )
    return {"dispatched": True}


@router.get("/notifications/log")
async def api_notifications_log(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    event: str = Query(""),
) -> dict:
    from sqlalchemy import desc, select

    from grabarr.db.session import session_scope
    from grabarr.notifications.models import NotificationLog

    async with session_scope() as session:
        q = select(NotificationLog).order_by(desc(NotificationLog.dispatched_at))
        if event:
            q = q.where(NotificationLog.event_type == event)
        rows = await session.execute(q.offset((page - 1) * size).limit(size))
        items = list(rows.scalars().all())
    return {
        "page": page,
        "size": size,
        "items": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "source_id": r.source_id,
                "title": r.title,
                "body": r.body,
                "severity": r.severity,
                "dispatched_at": r.dispatched_at.isoformat(),
                "dispatch_status": r.dispatch_status,
                "coalesced": r.coalesced,
            }
            for r in items
        ],
    }


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
