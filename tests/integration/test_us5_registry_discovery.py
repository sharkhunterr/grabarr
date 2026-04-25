"""US5 integration tests (spec SC-08, task T138/T139)."""

from __future__ import annotations

from grabarr.adapters.base import SourceAdapter
from grabarr.core.registry import discover_adapters, get_registered_adapters


def test_discover_picks_up_fixture_adapter() -> None:
    """Importing tests.fixtures.adapters registers FakeTestAdapter."""
    discover_adapters("tests.fixtures.adapters")
    registry = get_registered_adapters()
    assert "fake_test" in registry
    cls = registry["fake_test"]
    assert cls.display_name == "Fake Test Source"


def test_every_shipped_adapter_implements_protocol() -> None:
    """Every registered adapter class passes runtime Protocol check.

    Because ``SourceAdapter`` is ``@runtime_checkable``, any adapter
    that forgets to implement a required method fails this assertion
    at test time — caught before deployment.
    """
    for aid, cls in get_registered_adapters().items():
        assert issubclass(cls, object)
        # Runtime protocol check: the class must expose every
        # attribute + method the Protocol declares.
        for attr in (
            "id",
            "display_name",
            "supported_media_types",
            "requires_cf_bypass",
            "supports_member_key",
            "supports_authentication",
            "search",
            "get_download_info",
            "health_check",
            "get_config_schema",
            "get_quota_status",
        ):
            assert hasattr(cls, attr), f"{aid}: missing {attr}"


def test_welib_template_is_not_auto_loaded() -> None:
    """The ``.example`` suffix prevents accidental registry pollution."""
    registry = get_registered_adapters()
    assert "welib" not in registry, (
        "adapters/_welib_template.py.example should not auto-register — "
        "if this failed, the discovery predicate is broken"
    )
