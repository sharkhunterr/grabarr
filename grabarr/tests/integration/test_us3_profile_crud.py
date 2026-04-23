"""US3 integration test (task T112).

Exercises the full profile-lifecycle surface: duplicate → edit via
PATCH → verify Torznab endpoint is live → delete (protected + unprotected).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
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


def test_duplicate_profile_creates_editable_copy(app_client: TestClient) -> None:
    r = app_client.post(
        "/api/profiles/ebooks_general/duplicate",
        json={"new_slug": "my_ebooks_fr"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["slug"] == "my_ebooks_fr"
    assert data["is_default"] is False
    assert "api_key" in data  # one-time reveal

    # The new profile's Torznab endpoint must be immediately live.
    r = app_client.get("/torznab/my_ebooks_fr/api?t=caps")
    assert r.status_code == 200
    assert "<caps>" in r.text


def test_patch_profile_applies_filter_change(app_client: TestClient) -> None:
    # First duplicate so we have a non-default to edit (defaults are
    # editable too, but this mirrors the typical user flow).
    app_client.post(
        "/api/profiles/ebooks_general/duplicate", json={"new_slug": "ebooks_fr"}
    )
    r = app_client.patch(
        "/api/profiles/ebooks_fr",
        json={
            "name": "Ebooks (French)",
            "filters": {"languages": ["fr"], "preferred_formats": ["epub"]},
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Ebooks (French)"
    assert data["filters"]["languages"] == ["fr"]


def test_cannot_delete_default_profile(app_client: TestClient) -> None:
    r = app_client.delete("/api/profiles/ebooks_general")
    assert r.status_code == 403


def test_delete_duplicate_succeeds(app_client: TestClient) -> None:
    app_client.post(
        "/api/profiles/ebooks_general/duplicate", json={"new_slug": "disposable"}
    )
    r = app_client.delete("/api/profiles/disposable")
    assert r.status_code == 204

    r = app_client.get("/api/profiles/disposable")
    assert r.status_code == 404


def test_create_profile_minimum_fields(app_client: TestClient) -> None:
    r = app_client.post(
        "/api/profiles",
        json={
            "slug": "custom_ebooks",
            "name": "Custom Ebooks",
            "media_type": "ebook",
            "mode": "aggregate_all",
            "newznab_categories": [7020],
            "sources": [
                {"source_id": "internet_archive", "weight": 1.0, "timeout_seconds": 30,
                 "enabled": True, "skip_if_member_required": False},
            ],
            "filters": {"languages": [], "preferred_formats": []},
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["slug"] == "custom_ebooks"
    assert data["mode"] == "aggregate_all"


def test_edit_html_page_renders(app_client: TestClient) -> None:
    r = app_client.get("/profiles/ebooks_general/edit")
    assert r.status_code == 200
    assert "Edit Ebooks General" in r.text
    assert "source-list" in r.text
    r = app_client.get("/profiles/new")
    assert r.status_code == 200
    assert "New profile" in r.text
