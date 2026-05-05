"""Live read-only smoke against a running HA instance.

Usage:
    HA_URL=http://192.168.1.103:8123 \
    HA_TOKEN=eyJ... \
    python scripts/live_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request


def _get(path: str, base: str, token: str) -> dict | list:
    req = urllib.request.Request(
        f"{base}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main() -> int:
    base = os.environ.get("HA_URL")
    token = os.environ.get("HA_TOKEN")
    if not base or not token:
        print("Set HA_URL and HA_TOKEN.", file=sys.stderr)
        return 2

    eagle = _get("/api/states/sensor.eagle_200_meter_power_demand", base, token)
    climate = _get("/api/states/climate.thermostat", base, token)

    print(
        f"Eagle net (kW or W): {eagle['state']}"
        f" unit={eagle['attributes'].get('unit_of_measurement')}"
    )
    print(
        f"Climate state: {climate['state']}"
        f" target_high={climate['attributes'].get('target_temp_high')}"
    )

    # Peak window check
    from datetime import datetime
    from zoneinfo import ZoneInfo

    sys.path.insert(0, "custom_components/ha_power_control")
    from tou import is_peak  # type: ignore[import-not-found]

    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    print(f"Now: {now.isoformat()} in_peak={is_peak(now)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
