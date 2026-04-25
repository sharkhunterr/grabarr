"""US4 integration tests (spec FR-030, FR-031, FR-036)."""

from __future__ import annotations

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

    session_module.reset_engine()
    config_module._settings_singleton = None
    profiles_service._ADAPTER_INSTANCES.clear()


def test_healthz_reports_all_subsystems(app_client: TestClient) -> None:
    r = app_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "subsystems" in body
    sub = body["subsystems"]
    assert "database" in sub and sub["database"]["status"] == "ok"
    assert "libtorrent_session" in sub
    assert "adapters" in sub
    for aid in ("anna_archive", "internet_archive", "libgen", "zlibrary"):
        assert aid in sub["adapters"]


def test_sources_api_lists_all_adapters(app_client: TestClient) -> None:
    r = app_client.get("/api/sources")
    assert r.status_code == 200
    items = {it["id"] for it in r.json()["items"]}
    assert {"anna_archive", "internet_archive", "libgen", "zlibrary"} <= items


def test_notifications_apprise_crud(app_client: TestClient) -> None:
    r = app_client.post(
        "/api/notifications/apprise",
        json={
            "label": "ops-test",
            "url": "tgram://bot_token/chat_id",
            "subscribed_events": ["source_unhealthy", "download_failed"],
        },
    )
    assert r.status_code == 201
    uid = r.json()["id"]

    r = app_client.get("/api/notifications/apprise")
    items = r.json()["items"]
    assert any(u["id"] == uid for u in items)
    stored = next(u for u in items if u["id"] == uid)
    assert stored["label"] == "ops-test"
    assert "tgram" in stored["url_masked"]
    assert stored["url_masked"] != "tgram://bot_token/chat_id"

    r = app_client.delete(f"/api/notifications/apprise/{uid}")
    assert r.status_code == 204

    r = app_client.get("/api/notifications/apprise")
    assert all(u["id"] != uid for u in r.json()["items"])


def test_notification_dispatch_logs_attempts(app_client: TestClient) -> None:
    """Dispatch via /notifications/apprise/{id}/test which fires through
    the full pipeline; verify the log recorded an attempt."""
    # Add an Apprise URL that won't actually deliver (invalid scheme).
    r = app_client.post(
        "/api/notifications/apprise",
        json={
            "label": "test-dry-run",
            "url": "invalid-scheme://nowhere",
            "subscribed_events": ["source_recovered"],
        },
    )
    uid = r.json()["id"]

    r = app_client.post(f"/api/notifications/apprise/{uid}/test")
    assert r.status_code == 200

    r = app_client.get("/api/notifications/log")
    items = r.json()["items"]
    assert any(it["event_type"] == "source_recovered" for it in items)


def test_sources_ui_renders(app_client: TestClient) -> None:
    r = app_client.get("/sources")
    assert r.status_code == 200
    assert "Sources" in r.text
    for aid in ("anna_archive", "internet_archive", "libgen", "zlibrary"):
        assert aid in r.text


def test_notifications_ui_renders(app_client: TestClient) -> None:
    r = app_client.get("/notifications")
    assert r.status_code == 200
    assert "Notifications" in r.text
    assert "Apprise destinations" in r.text
