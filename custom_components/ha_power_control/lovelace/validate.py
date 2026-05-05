"""Validate the bundled Lovelace dashboard YAML.

Usage: python -m custom_components.ha_power_control.lovelace.validate dashboard.yaml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# Entity-id regex must match HA conventions
_VALID_ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def _walk(obj, found: set[str]) -> None:
    if isinstance(obj, dict):
        if "entity" in obj and isinstance(obj["entity"], str):
            found.add(obj["entity"])
        for v in obj.values():
            _walk(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, found)


def main(path: str) -> int:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).parent / path
    if not p.exists():
        print(f"FAIL: {path} not found", file=sys.stderr)
        return 1
    data = yaml.safe_load(p.read_text())
    if "views" not in data or not isinstance(data["views"], list):
        print("FAIL: dashboard YAML missing 'views' list", file=sys.stderr)
        return 1
    found: set[str] = set()
    _walk(data, found)
    bad = [e for e in found if not _VALID_ENTITY_ID.match(e)]
    if bad:
        print(f"FAIL: malformed entity_ids: {bad}", file=sys.stderr)
        return 1
    print(f"OK: {len(found)} entity references, all well-formed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "dashboard.yaml"))
