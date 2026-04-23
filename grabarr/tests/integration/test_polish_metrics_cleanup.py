"""Phase 8 tests: /metrics exposition + cleanup sweeper."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GRABARR_CONFIG_PATH", str(tmp_path / "nonexistent.yaml"))
    monkeypatch.setenv("GRABARR_SERVER__DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GRABARR_SERVER__DOWNLOADS_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("GRABARR_TORRENT_MODE", "webseed")
    (tmp_path / "data").mkdir()
    (tmp_path / "downloads" / "incoming").mkdir(parents=True)
    (tmp_path / "downloads" / "ready").mkdir(parents=True)

    from grabarr.core import config as config_module
    from grabarr.db import session as session_module
    from grabarr.profiles import service as profiles_service

    config_module._settings_singleton = None
    session_module.reset_engine()
    profiles_service._ADAPTER_INSTANCES.clear()

    import grabarr.adapters  # noqa: F401

    from grabarr.api.app import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


def test_metrics_endpoint_exposes_expected_series(app_client: TestClient) -> None:
    r = app_client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    # Spec SC-10: > 50 distinct series when fully loaded. Just verify
    # the core families are present here; load dims on top to hit 50+
    # in production.
    required_substrings = [
        "grabarr_searches_total",
        "grabarr_downloads_total",
        "grabarr_bypass_invocations_total",
        "grabarr_errors_total",
        "grabarr_source_response_duration_seconds",
        "grabarr_download_duration_seconds",
        "grabarr_bypass_duration_seconds",
        "grabarr_active_downloads",
        "grabarr_seeded_torrents_total",
        "grabarr_queue_depth",
        "grabarr_source_healthy",
        "grabarr_quota_remaining",
    ]
    for needle in required_substrings:
        assert needle in body, f"/metrics missing {needle}"


def test_cleanup_sweeper_removes_expired_records(app_client: TestClient) -> None:
    import asyncio

    from grabarr.bypass.models import BypassSession
    from grabarr.db.session import session_scope
    from grabarr.downloads.cleanup import sweep_once

    # Seed an expired bypass-session entry.
    async def setup() -> None:
        async with session_scope() as session:
            session.add(
                BypassSession(
                    domain="expired.example",
                    user_agent="UA",
                    cf_clearance="cookie",
                    issued_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
                    expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5),
                    mode_used="external",
                    hit_count=0,
                )
            )

    async def run() -> dict:
        await setup()
        return await sweep_once()

    stats = asyncio.run(run())
    assert stats["bypass_sessions"] >= 1
