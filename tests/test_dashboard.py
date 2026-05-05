"""Tests for the Lovelace dashboard validator."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from custom_components.ha_power_control.lovelace.validate import _walk, main

DASHBOARD_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "ha_power_control"
    / "lovelace"
    / "dashboard.yaml"
)


def test_dashboard_yaml_exists() -> None:
    assert DASHBOARD_PATH.exists(), f"dashboard.yaml not found at {DASHBOARD_PATH}"


def test_dashboard_yaml_parses() -> None:
    data = yaml.safe_load(DASHBOARD_PATH.read_text())
    assert isinstance(data, dict)
    assert "views" in data
    assert isinstance(data["views"], list)
    assert len(data["views"]) > 0


def test_dashboard_has_title() -> None:
    data = yaml.safe_load(DASHBOARD_PATH.read_text())
    assert data.get("title") == "Power Control"


def test_dashboard_entity_references_well_formed() -> None:
    """All entity: references must match HA entity-id pattern."""
    import re

    valid_re = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
    data = yaml.safe_load(DASHBOARD_PATH.read_text())
    found: set[str] = set()
    _walk(data, found)
    assert len(found) > 0, "No entity references found in dashboard"
    bad = [e for e in found if not valid_re.match(e)]
    assert bad == [], f"Malformed entity_ids: {bad}"


def test_dashboard_references_integration_entities() -> None:
    """Spot-check that key integration entities are referenced."""
    data = yaml.safe_load(DASHBOARD_PATH.read_text())
    found: set[str] = set()
    _walk(data, found)
    expected = {
        "sensor.ha_power_control_net_power",
        "binary_sensor.ha_power_control_in_peak_window",
        "select.ha_power_control_operating_mode",
        "switch.ha_power_control_dry_run",
    }
    missing = expected - found
    assert missing == set(), f"Expected entities not in dashboard: {missing}"


def test_validate_main_returns_zero_for_valid_dashboard() -> None:
    """validate.main() returns 0 for the bundled dashboard."""
    result = main(str(DASHBOARD_PATH))
    assert result == 0


def test_validate_main_returns_one_for_missing_file(tmp_path: pytest.TempPathFactory) -> None:
    result = main(str(tmp_path / "nonexistent.yaml"))
    assert result == 1


def test_validate_main_returns_one_for_missing_views(tmp_path: pytest.TempPathFactory) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("title: Test\n")
    result = main(str(bad_yaml))
    assert result == 1


def test_validate_main_returns_one_for_malformed_entity(tmp_path: pytest.TempPathFactory) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "title: Test\nviews:\n  - title: v\n    cards:\n      - entity: 'INVALID ENTITY'\n"
    )
    result = main(str(bad_yaml))
    assert result == 1


def test_walk_collects_nested_entities() -> None:
    data = {
        "views": [
            {
                "cards": [
                    {"entity": "sensor.foo"},
                    {"entities": [{"entity": "switch.bar"}]},
                ]
            }
        ]
    }
    found: set[str] = set()
    _walk(data, found)
    assert found == {"sensor.foo", "switch.bar"}
