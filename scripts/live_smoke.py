"""Live read-only smoke against a running HA instance.

Usage (from project root):
    HA_URL=http://<your-ha-ip>:8123 \
    HA_TOKEN=eyJ... \
    python scripts/live_smoke.py

Entity IDs assume the integration device is named "HA Power Control".
If HA auto-renamed any entity, adjust below.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

_LA = ZoneInfo("America/Los_Angeles")
_PASS = "PASS"
_WARN = "WARN"
_FAIL = "FAIL"


def _fetch(entity_id: str, base: str, token: str) -> dict | None:
    req = urllib.request.Request(
        f"{base}/api/states/{entity_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


def _check(entity_id: str, base: str, token: str) -> tuple[str, str, dict]:
    """Returns (status, detail, attributes)."""
    data = _fetch(entity_id, base, token)
    if data is None:
        return _FAIL, "not found (integration not installed?)", {}
    state = data.get("state", "")
    attrs = data.get("attributes", {})
    if state in ("unavailable", "unknown"):
        return _FAIL, f"state={state}", attrs
    return _PASS, f"state={state}", attrs


def _row(label: str, status: str, detail: str) -> None:
    icon = {_PASS: "✓", _WARN: "~", _FAIL: "✗"}.get(status, "?")
    print(f"  {icon} [{status}] {label:<45} {detail}")


def main() -> int:
    base = os.environ.get("HA_URL", "").rstrip("/")
    token = os.environ.get("HA_TOKEN", "")
    if not base or not token:
        print("Set HA_URL and HA_TOKEN.", file=sys.stderr)
        print("  HA_URL=http://<your-ha-ip>:8123", file=sys.stderr)
        print("  HA_TOKEN=<long-lived access token from HA profile page>", file=sys.stderr)
        return 2

    failures = 0
    warnings = 0

    # ── Upstream entities ──────────────────────────────────────────────────
    print("\n── Upstream entities ─────────────────────────────────────────────")
    upstream = [
        ("sensor.eagle_200_meter_power_demand", None),
        ("sensor.eagle_200_total_meter_energy_delivered", None),
        ("sensor.eagle_200_total_meter_energy_received", None),
        ("climate.thermostat", None),
    ]
    for eid, _ in upstream:
        status, detail, attrs = _check(eid, base, token)
        if status == _FAIL:
            failures += 1
        unit = attrs.get("unit_of_measurement", "")
        if unit:
            detail += f" ({unit})"
        if eid == "climate.thermostat" and status == _PASS:
            th = attrs.get("target_temp_high")
            tl = attrs.get("target_temp_low")
            tc = attrs.get("current_temperature")
            detail += f" | high={th} low={tl} current={tc}"
        _row(eid, status, detail)

    # ── Integration sensors (P1) ───────────────────────────────────────────
    print("\n── Integration sensors (P1) ──────────────────────────────────────")
    p1_sensors = [
        "sensor.ha_power_control_net_power",
        "sensor.ha_power_control_export_power",
        "sensor.ha_power_control_solar_power",
        "sensor.ha_power_control_mean_indoor_temperature",
        "sensor.ha_power_control_projected_true_up",
        "sensor.ha_power_control_today_s_peak_savings",
    ]
    for eid in p1_sensors:
        status, detail, attrs = _check(eid, base, token)
        if status == _FAIL:
            failures += 1
        unit = attrs.get("unit_of_measurement", "")
        if unit:
            detail += f" ({unit})"
        _row(eid.split(".")[-1], status, detail)

    # ── P2 climate control entities ────────────────────────────────────────
    print("\n── P2 climate control ────────────────────────────────────────────")

    # dry_run — must be ON for safe first install
    status, detail, attrs = _check("switch.ha_power_control_dry_run", base, token)
    if status == _FAIL:
        failures += 1
    elif detail == "state=off":
        status = _WARN
        detail += "  ← writes are LIVE (no-op logging disabled)"
        warnings += 1
    _row("switch.ha_power_control_dry_run", status, detail)

    # climate_override_enabled — must be OFF for safe first install
    status, detail, attrs = _check("switch.ha_power_control_climate_override_enabled", base, token)
    if status == _FAIL:
        failures += 1
    elif detail == "state=on":
        status = _WARN
        detail += "  ← climate writes enabled"
        warnings += 1
    _row("switch.ha_power_control_climate_override_enabled", status, detail)

    # owns_climate — should be OFF on fresh start (no cycle in progress)
    status, detail, attrs = _check("binary_sensor.ha_power_control_owns_climate", base, token)
    if status == _FAIL:
        failures += 1
    elif detail == "state=on":
        status = _WARN
        detail += "  ← precool or peak-hold cycle active"
        warnings += 1
    _row("binary_sensor.ha_power_control_owns_climate", status, detail)

    # in_peak_window
    status, detail, attrs = _check("binary_sensor.ha_power_control_in_peak_window", base, token)
    if status == _FAIL:
        failures += 1
    _row("binary_sensor.ha_power_control_in_peak_window", status, detail)

    # climate_healthy
    status, detail, attrs = _check("binary_sensor.ha_power_control_climate_healthy", base, token)
    if status == _FAIL:
        failures += 1
    elif detail == "state=off":
        status = _WARN
        detail += "  ← thermostat entity unreachable or in bad state"
        warnings += 1
    _row("binary_sensor.ha_power_control_climate_healthy", status, detail)

    # precool_offset_f
    status, detail, attrs = _check("number.ha_power_control_precool_offset", base, token)
    if status == _FAIL:
        failures += 1
    _row("number.ha_power_control_precool_offset", status, detail)

    # ── P2 peak window (local check) ───────────────────────────────────────
    print("\n── Peak window (local policy check) ──────────────────────────────")
    sys.path.insert(0, "custom_components/ha_power_control")
    try:
        from tou import is_peak  # type: ignore[import-not-found]

        now = datetime.now(_LA)
        in_peak = is_peak(now)
        print(f"  Now (LA): {now.strftime('%Y-%m-%d %H:%M %Z')}  in_peak={in_peak}")
    except ImportError:
        print("  WARN: could not import tou module — run from project root")
        warnings += 1

    # ── Summary ────────────────────────────────────────────────────────────
    print()
    if failures:
        print(
            f"RESULT: FAIL — {failures} entity/entities not found or unavailable."
            "\n  → Install the integration via HACS and restart HA, then re-run."
        )
        return 1
    if warnings:
        print(f"RESULT: PASS with {warnings} warning(s) — see ~ lines above.")
        return 0
    print("RESULT: PASS — all entities reachable, safe defaults confirmed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
