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

from grabarr.core.logging import get_log_file_path, ring_snapshot, setup_logger
from grabarr.profiles.models import Profile
from grabarr.profiles.orchestrator import test_profile as run_test_profile
from grabarr.profiles.service import (
    ProfileDefaultProtected,
    ProfileNotFound,
    ProfileSlugConflict,
    create_profile,
    delete_profile,
    duplicate_profile,
    get_or_mint_api_key,
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
        # Per-adapter runtime knobs (mirror, etc.). Keeps the per-source
        # UI decoupled from the generic settings page.
        runtime: dict[str, Any] = {}
        if aid == "anna_archive":
            from grabarr.core.settings_service import get_sync as _g

            try:
                from grabarr.vendor.shelfmark.core.mirrors import DEFAULT_AA_MIRRORS
                from grabarr.vendor.shelfmark.download import network as _net

                active_base = getattr(_net, "_aa_base_url", None)
                mirrors = list(DEFAULT_AA_MIRRORS)
            except Exception:  # noqa: BLE001
                active_base = None
                mirrors = [
                    "https://annas-archive.gl",
                    "https://annas-archive.pk",
                    "https://annas-archive.vg",
                    "https://annas-archive.gd",
                ]
            override = (_g("sources.anna_archive.aa_mirror_urls", "") or "").strip()
            if override:
                mirrors = [u.strip() for u in override.split(",") if u.strip()]
            runtime = {
                "aa_base_url": _g("sources.anna_archive.aa_base_url", "auto"),
                "aa_active_base": active_base,
                "aa_known_mirrors": mirrors,
            }
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
                "runtime": runtime,
            }
        )
    return {"items": items}


@router.patch("/sources/anna_archive/mirror")
async def api_set_aa_mirror(body: dict[str, Any] = Body(default_factory=dict)) -> dict:
    """Pin AA to a specific mirror (or "auto") + refresh Shelfmark live.

    Body: ``{"aa_base_url": "https://annas-archive.gl" | "auto",
             "aa_mirror_urls": "comma,separated" (optional)}``
    """
    from grabarr.core.settings_service import update_many

    patch: dict[str, Any] = {}
    if "aa_base_url" in body:
        val = (body.get("aa_base_url") or "auto").strip() or "auto"
        patch["sources.anna_archive.aa_base_url"] = val
    if "aa_mirror_urls" in body:
        patch["sources.anna_archive.aa_mirror_urls"] = (body.get("aa_mirror_urls") or "").strip()
    if not patch:
        raise HTTPException(status_code=400, detail="no mirror fields in request")
    await update_many(patch)
    # Tell Shelfmark to re-read the config + re-select the active mirror
    # without waiting for a process restart.
    active_base = None
    try:
        from grabarr.vendor.shelfmark.download import network as _net

        _net.init_aa(force=True)
        active_base = getattr(_net, "_aa_base_url", None)
    except Exception as exc:  # noqa: BLE001
        _log.warning("init_aa(force=True) raised: %s", exc)
    return {
        "aa_base_url": patch.get("sources.anna_archive.aa_base_url"),
        "aa_mirror_urls": patch.get("sources.anna_archive.aa_mirror_urls"),
        "aa_active_base": active_base,
    }


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


# ---- Settings ----------------------------------------------------------


@router.get("/settings")
async def api_list_settings() -> dict:
    from grabarr.core.settings_service import get_all

    data = await get_all()
    # Redact secret-looking values.
    redacted = dict(data)
    for k in list(redacted.keys()):
        if any(s in k for s in ("key", "secret", "cookie", "token", "password")):
            redacted[k] = "***"
    return redacted


@router.patch("/settings")
async def api_patch_settings(body: dict[str, Any] = Body(...)) -> dict:
    from grabarr.core.settings_service import update_many

    result = await update_many(body)

    # Apply live changes that Shelfmark caches internally — DNS resolver
    # selection, AA mirror selection, SSL-validation mode. Without this,
    # the user would need to restart the server for these to take effect.
    network_keys = {
        "network.use_doh",
        "network.custom_dns",
        "sources.anna_archive.aa_base_url",
        "sources.anna_archive.aa_mirror_urls",
    }
    if network_keys.intersection(body.keys()):
        try:
            from grabarr.vendor.shelfmark.download import network as _net

            _net.init(force=True)
        except Exception as exc:  # noqa: BLE001
            _log.warning("network.init(force=True) raised: %s", exc)

    return result


# ---- Downloads history -------------------------------------------------


@router.get("/downloads")
async def api_list_downloads(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    status: str = Query(""),
    profile: str = Query(""),
    source: str = Query(""),
    q: str = Query(""),
) -> dict:
    from sqlalchemy import desc, func, or_, select

    from grabarr.db.session import session_scope
    from grabarr.downloads.models import Download
    from grabarr.profiles.models import Profile

    async with session_scope() as session:
        stmt = select(Download).order_by(desc(Download.started_at))
        count_stmt = select(func.count(Download.id))

        profile_slug_by_id: dict[str, str] = {}
        if profile:
            p_row = await session.execute(select(Profile).where(Profile.slug == profile))
            p = p_row.scalar_one_or_none()
            if p is None:
                return {"page": page, "size": size, "total": 0, "items": []}
            stmt = stmt.where(Download.profile_id == p.id)
            count_stmt = count_stmt.where(Download.profile_id == p.id)
        if status:
            stmt = stmt.where(Download.status == status)
            count_stmt = count_stmt.where(Download.status == status)
        if source:
            stmt = stmt.where(Download.source_id == source)
            count_stmt = count_stmt.where(Download.source_id == source)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Download.title.ilike(like), Download.author.ilike(like)))
            count_stmt = count_stmt.where(
                or_(Download.title.ilike(like), Download.author.ilike(like))
            )

        rows = await session.execute(stmt.offset((page - 1) * size).limit(size))
        items = list(rows.scalars().all())
        total = (await session.execute(count_stmt)).scalar_one()

        profile_ids = {it.profile_id for it in items}
        if profile_ids:
            p_rows = await session.execute(
                select(Profile).where(Profile.id.in_(profile_ids))
            )
            profile_slug_by_id = {p.id: p.slug for p in p_rows.scalars().all()}

    return {
        "page": page,
        "size": size,
        "total": total,
        "items": [
            {
                "id": it.id,
                "token": it.token,
                "profile_slug": profile_slug_by_id.get(it.profile_id, "?"),
                "source_id": it.source_id,
                "title": it.title,
                "author": it.author,
                "year": it.year,
                "filename": it.filename,
                "size_bytes": it.size_bytes,
                "status": it.status,
                "download_mode": it.download_mode,
                "torrent_mode": it.torrent_mode,
                "info_hash": it.info_hash,
                "failure_reason": it.failure_reason,
                "started_at": it.started_at.isoformat() if it.started_at else None,
                "completed_at": it.completed_at.isoformat() if it.completed_at else None,
                "file_available": bool(it.file_path),
            }
            for it in items
        ],
    }


@router.post("/downloads/bulk-delete")
async def api_bulk_delete_downloads(body: dict[str, Any] = Body(default_factory=dict)) -> dict:
    """Bulk-delete downloads + their staged files.

    Body (all optional, combinable):
      - ``status``: one of queued/resolving/downloading/verifying/ready/
        seeding/completed/failed — delete only rows matching. If omitted,
        every download row is deleted. Pass ``"all"`` to be explicit.
      - ``include_torrents``: bool, default True — also drop the matching
        torrents rows.
      - ``include_files``: bool, default True — unlink on-disk files.

    Returns ``{"deleted": N, "files_removed": M}``.
    """
    import os
    from pathlib import Path
    from sqlalchemy import delete as sa_delete, select

    from grabarr.db.session import session_scope
    from grabarr.downloads.models import Download
    from grabarr.torrents.models import Torrent

    target_status = body.get("status")
    if target_status in ("all", "", None):
        target_status = None
    elif target_status not in {
        "queued", "resolving", "downloading", "verifying",
        "ready", "seeding", "completed", "failed",
    }:
        raise HTTPException(status_code=400, detail=f"invalid status: {target_status}")

    include_torrents = bool(body.get("include_torrents", True))
    include_files = bool(body.get("include_files", True))

    deleted = 0
    files_removed = 0
    async with session_scope() as session:
        q = select(Download)
        if target_status:
            q = q.where(Download.status == target_status)
        rows = (await session.execute(q)).scalars().all()
        deleted = len(rows)
        for dl in rows:
            if include_files and dl.file_path:
                try:
                    p = Path(dl.file_path)
                    if p.exists():
                        p.unlink(missing_ok=True)
                        files_removed += 1
                        # best-effort: remove the empty per-token parent dir
                        try:
                            p.parent.rmdir()
                        except OSError:
                            pass
                except OSError:
                    pass
            await session.delete(dl)
        if include_torrents and target_status is None:
            # Drop any orphan torrent rows (download_id can be NULL after
            # an older migration bug; belt and braces).
            await session.execute(sa_delete(Torrent))

    return {"deleted": deleted, "files_removed": files_removed}


@router.post("/downloads/{download_id}/retry")
async def api_retry_download(download_id: str) -> dict:
    """Re-queue a failed or cancelled download with a fresh token.

    Looks up the original source_id + external_id + profile, creates
    a new SearchToken, and returns the torznab URL the *arr client
    (or you) can GET to actually re-run the grab. The old Download
    row is left intact for history.
    """
    import secrets
    from sqlalchemy import select

    from grabarr.db.session import session_scope
    from grabarr.downloads.models import Download
    from grabarr.downloads.search_tokens import SearchToken
    from grabarr.profiles.models import Profile

    async with session_scope() as session:
        row = await session.execute(select(Download).where(Download.id == download_id))
        dl = row.scalar_one_or_none()
        if dl is None:
            raise HTTPException(status_code=404, detail="download not found")
        prof = await session.execute(
            select(Profile).where(Profile.id == dl.profile_id)
        )
        profile = prof.scalar_one_or_none()
        if profile is None:
            raise HTTPException(status_code=404, detail="profile no longer exists")

        new_token = secrets.token_urlsafe(24)
        session.add(
            SearchToken(
                token=new_token,
                profile_slug=profile.slug,
                source_id=dl.source_id,
                external_id=dl.external_id,
                media_type=dl.media_type,
                title=dl.title,
                author=dl.author,
                year=dl.year,
                size_bytes=dl.size_bytes,
            )
        )
    return {
        "new_token": new_token,
        "profile_slug": profile.slug,
        "torrent_url": f"/torznab/{profile.slug}/download/{new_token}.torrent",
        "message": (
            "GET the torrent_url to execute the grab. Prowlarr / Bookshelf "
            "can also be pointed at it manually."
        ),
    }


@router.post("/downloads/{download_id}/cancel")
async def api_cancel_download(download_id: str) -> dict:
    """Mark a non-terminal grab as failed with a 'cancelled by user' reason.

    Can't truly kill the worker thread (Python threads don't cancel),
    but flipping the DB row lets the active-grabs UI stop showing it
    and frees the slot. The underlying Shelfmark cascade will run to
    its own timeout (max 240 s) in the background; the reservation
    above then silently drops.
    """
    import datetime as dt
    from sqlalchemy import select

    from grabarr.db.session import session_scope
    from grabarr.downloads.models import Download

    async with session_scope() as session:
        row = await session.execute(select(Download).where(Download.id == download_id))
        dl = row.scalar_one_or_none()
        if dl is None:
            raise HTTPException(status_code=404, detail="download not found")
        terminal = {"seeding", "completed", "failed"}
        if dl.status in terminal:
            return {"status": dl.status, "changed": False}
        dl.status = "failed"
        dl.failure_reason = "cancelled by user"
        dl.completed_at = dt.datetime.now(dt.UTC)
    return {"status": "failed", "changed": True}


@router.delete("/downloads/{download_id}", status_code=204)
async def api_delete_download(download_id: str) -> None:
    from pathlib import Path

    from sqlalchemy import select

    from grabarr.db.session import session_scope
    from grabarr.downloads.models import Download

    async with session_scope() as session:
        row = await session.execute(select(Download).where(Download.id == download_id))
        obj = row.scalar_one_or_none()
        if obj is None:
            raise HTTPException(status_code=404, detail="not found")
        if obj.file_path:
            try:
                Path(obj.file_path).unlink(missing_ok=True)
            except OSError:
                pass
        await session.delete(obj)


# ---- Stats -------------------------------------------------------------


@router.get("/stats/overview")
async def api_stats_overview() -> dict:
    from sqlalchemy import func, select

    from grabarr.db.session import session_scope
    from grabarr.downloads.models import Download
    from grabarr.torrents.models import Torrent

    async with session_scope() as session:
        total = (await session.execute(select(func.count(Download.id)))).scalar_one()
        succeeded = (
            await session.execute(
                select(func.count(Download.id)).where(
                    Download.status.in_(["seeding", "completed"])
                )
            )
        ).scalar_one()
        failed = (
            await session.execute(
                select(func.count(Download.id)).where(Download.status == "failed")
            )
        ).scalar_one()
        active = (
            await session.execute(
                select(func.count(Download.id)).where(
                    Download.status.in_(["queued", "resolving", "downloading", "verifying"])
                )
            )
        ).scalar_one()
        seeded = (await session.execute(select(func.count(Torrent.info_hash)))).scalar_one()

        rows = await session.execute(
            select(Download.source_id, Download.status, func.count(Download.id)).group_by(
                Download.source_id, Download.status
            )
        )
        per_source: dict[str, dict[str, int]] = {}
        for source_id, status, count in rows.all():
            per_source.setdefault(source_id, {})[status] = count

    return {
        "downloads_total": total,
        "downloads_succeeded": succeeded,
        "downloads_failed": failed,
        "active_downloads": active,
        "active_seeds": seeded,
        "per_source": per_source,
    }


@router.get("/stats/top-queries")
async def api_stats_top_queries(limit: int = Query(10, ge=1, le=50)) -> dict:
    from sqlalchemy import desc, func, select

    from grabarr.db.session import session_scope
    from grabarr.downloads.models import Download

    async with session_scope() as session:
        rows = await session.execute(
            select(Download.title, func.count(Download.id).label("n"))
            .group_by(Download.title)
            .order_by(desc("n"))
            .limit(limit)
        )
    return {"items": [{"title": t, "count": c} for t, c in rows.all()]}


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

    plaintext = await get_or_mint_api_key(profile)
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


@router.get("/debug/shelfmark-config")
async def api_debug_shelfmark_config() -> dict:
    """Dump whatever the Shelfmark config proxy actually returns right now.

    Diagnostic for the "bridge says X but Shelfmark sees Y" class of
    bugs. Reads the SAME proxy Shelfmark's vendored code reads, so the
    values here are what bypasser/network/cascade will actually use.
    """
    from grabarr.vendor.shelfmark._grabarr_adapter import shelfmark_config_proxy as proxy

    keys = [
        "USING_EXTERNAL_BYPASSER", "USE_CF_BYPASS",
        "EXT_BYPASSER_URL", "EXT_BYPASSER_PATH", "EXT_BYPASSER_TIMEOUT",
        "AA_BASE_URL", "AA_MIRROR_URLS", "AA_DONATOR_KEY",
        "USE_DOH", "DOH_SERVER", "CUSTOM_DNS",
        "MAX_RETRY", "DEFAULT_SLEEP", "SOURCE_PRIORITY",
    ]
    return {k: proxy.get(k, "<MISSING>") for k in keys}


# ---- Bypass (FlareSolverr) ---------------------------------------------


@router.post("/bypass/test")
async def api_bypass_test(body: dict[str, Any] = Body(default_factory=dict)) -> dict:
    """Probe FlareSolverr.

    Request body (all optional):
      - ``url``: host[:port] of FlareSolverr. Falls back to
        ``GRABARR_SHELFMARK_EXT_BYPASSER_URL`` env, then the
        ``bypass.flaresolverr_url`` setting, then the Shelfmark default.
      - ``target``: page to fetch through the bypasser (default:
        ``https://annas-archive.gl/``).

    Returns ``{status, endpoint, probe_target, elapsed_ms,
    flaresolverr_version?, message?}``. ``status`` is ``"ok"`` when the
    round-trip succeeds and FlareSolverr returns a non-empty HTML body.
    """
    import os
    import time

    import httpx

    # 1. Pick endpoint.
    raw = (body.get("url") or "").strip() or None
    if not raw:
        raw = os.environ.get("GRABARR_SHELFMARK_EXT_BYPASSER_URL") or None
    if not raw:
        # Fall back to the bypass.flaresolverr_url setting via admin API shape.
        from grabarr.core.settings_model import Setting
        from grabarr.db.session import session_scope
        from sqlalchemy import select

        async with session_scope() as session:
            row = await session.execute(
                select(Setting.value).where(Setting.key == "bypass.flaresolverr_url")
            )
            raw = row.scalar_one_or_none()
    if not raw:
        raw = "http://flaresolverr:8191"

    # Accept host[:port] with or without trailing /v1.
    endpoint = raw.rstrip("/")
    if endpoint.endswith("/v1"):
        v1 = endpoint
    else:
        v1 = f"{endpoint}/v1"

    target = body.get("target") or "https://annas-archive.gl/"
    # Pick up the user-configured maxTimeout (ms) from the settings cache.
    from grabarr.core.settings_service import get_sync as _get_sync

    try:
        max_timeout_ms = int(body.get("max_timeout_ms") or _get_sync("bypass.flaresolverr_timeout_ms", 120000))
    except (TypeError, ValueError):
        max_timeout_ms = 120000
    # httpx timeout = maxTimeout + 15 s buffer for FlareSolverr overhead.
    client_timeout = (max_timeout_ms / 1000) + 15

    # 2. POST request.get to FlareSolverr.
    payload = {"cmd": "request.get", "url": target, "maxTimeout": max_timeout_ms}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=client_timeout) as client:
            r = await client.post(
                v1,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
    except httpx.ConnectError as exc:
        return {
            "status": "unreachable",
            "endpoint": v1,
            "probe_target": target,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "message": f"Could not connect: {exc}",
        }
    except httpx.TimeoutException:
        return {
            "status": "timeout",
            "endpoint": v1,
            "probe_target": target,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "message": f"No response within {int(client_timeout)} s — is FlareSolverr running?",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "endpoint": v1,
            "probe_target": target,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "message": str(exc),
        }
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # 3. Parse the FlareSolverr response envelope.
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return {
            "status": "bad_response",
            "endpoint": v1,
            "probe_target": target,
            "elapsed_ms": elapsed_ms,
            "message": f"HTTP {r.status_code}; body was not JSON ({r.text[:200]})",
        }

    fs_status = data.get("status")
    version = data.get("version")
    if fs_status != "ok":
        return {
            "status": "failed",
            "endpoint": v1,
            "probe_target": target,
            "elapsed_ms": elapsed_ms,
            "flaresolverr_version": version,
            "message": data.get("message") or f"FlareSolverr status={fs_status}",
        }
    solution = data.get("solution") or {}
    html = solution.get("response") or ""
    return {
        "status": "ok",
        "endpoint": v1,
        "probe_target": target,
        "elapsed_ms": elapsed_ms,
        "flaresolverr_version": version,
        "message": (
            f"solved in {solution.get('status', '?')} — "
            f"{len(html)} bytes of HTML returned"
        ),
    }


# ---- Torznab activity -------------------------------------------------


@router.get("/torznab/activity")
async def api_torznab_activity() -> dict:
    """Return the recent ring-buffer of torznab queries seen by the server.

    Lets you confirm what Prowlarr / Bookshelf actually sent, how many
    items Grabarr returned for that exact query, and how long it took —
    without crawling the access log.
    """
    from grabarr.api.torznab import recent_torznab_activity

    items = recent_torznab_activity()
    return {"items": items, "count": len(items)}


# ---- Logs --------------------------------------------------------------


@router.get("/logs")
async def api_logs(
    lines: int = Query(200, ge=1, le=2000),
    level: str | None = Query(None, description="DEBUG|INFO|WARNING|ERROR|CRITICAL"),
    logger: str | None = Query(None, description="Only loggers starting with this prefix"),
    since: str | None = Query(None, description="ISO ts — return only entries strictly after it"),
) -> dict:
    """Return the tail of the in-memory log ring buffer.

    Secrets are redacted via ``RedactionFilter`` before entering the ring,
    so what comes back is safe to display in the UI. The on-disk
    ``grabarr.log`` file holds the full history (rotated at 10 MB).
    """
    items = ring_snapshot(lines=lines, level=level, logger_prefix=logger)
    if since:
        items = [i for i in items if i["ts"] > since]
    path = get_log_file_path()
    return {
        "items": items,
        "count": len(items),
        "file": str(path) if path else None,
    }
