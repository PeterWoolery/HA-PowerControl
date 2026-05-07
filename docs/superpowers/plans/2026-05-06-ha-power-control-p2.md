# HA Power Control P2 — Climate Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the climate controller (Mode B — precool + peak-hold) with crash-safe persistence, external-override detection, and dry-run gating, releasing as v0.2.0.

**Architecture:**
- Pure-Python policy module `policy/climate.py` exposes `decide(inputs) -> Action` (no HA imports → trivially unit-testable).
- Thin async runner `policy/climate_runner.py` translates each `Action` into `climate.set_temperature` service calls and Store writes.
- Coordinator calls the runner every tick after assembling `PowerState`. Sustained-export tracking lives on the coordinator (single instance owns the timer).
- All persistent state (`captured_originals`, `precool_active`, `peak_hold_active`, `precool_ran_this_cycle`, `last_write_record`, `cooldown_until`) lives in `HAPowerControlStore` under key `ha_power_control.climate_state` (already declared in `const.py`).
- Dry-run and climate-override-enabled switches (P1 in-memory state) get promoted to `entry.options` so policy reads from a single source of truth.

**Tech Stack:** Python 3.12, Home Assistant 2026.4+, `pytest-homeassistant-custom-component`, `homeassistant.helpers.storage.Store`, ruff.

**Out of scope for P2:** Mode A preset maintenance, battery state machine (P3), ROI recommender (P4), multi-zone (P5).

---

## Execution status (P2 complete)

All 16 tasks shipped. v0.2.0 tagged on branch `p2/climate-controller`.

| Task | Commits |
|---|---|
| T1 — switch persistence | 00edd7e, e39b448 |
| T2 — sustained-export tracker | 57f3a76, 2828a93 |
| T3 — store schema | 644b41f |
| T4 — policy scaffold | 82eeb6c, b289d0f |
| T5 — precool entry | 724a9ea |
| T6 — peak-hold transition | e05e757 |
| T7 — restoration paths | 2ebc565 |
| T8 — hard exit on temp ceiling | a3f1426 |
| T9 — drift + cooldown | 0fb20e7 |
| T10 — clamp | 0cfe313 |
| T11 — runner | 32d01a0 |
| T12 — coordinator wiring | f8ef544 |
| T13 — startup restore | 3c9fae7 |
| T14 — owns_climate + precool_offset | 68da2d1 |
| T15 — e2e cycle test | 5ea429a |
| Audit fixes (clamp + DRY + tz + magic 600 + dead branch) | 45c8e10, 2ad5483 |
| T16 — release | ccbabdd |

Final gate: 110 tests passing, 95.54% coverage, ruff clean.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `custom_components/ha_power_control/policy/__init__.py` | Create | Package marker. |
| `custom_components/ha_power_control/policy/climate.py` | Create | Pure-Python `decide()`, `Action`, `ClimateInputs`, `ClimatePersisted`. |
| `custom_components/ha_power_control/policy/climate_runner.py` | Create | Async executor: takes Action → service calls + Store writes. |
| `custom_components/ha_power_control/coordinator.py` | Modify | Track `export_run_started_at`; call runner each tick. |
| `custom_components/ha_power_control/store.py` | Modify | Schema helpers for climate state (`get_climate_state`, `set_climate_state`). |
| `custom_components/ha_power_control/__init__.py` | Modify | Restore-on-startup: replay persisted originals before forwarding platforms. |
| `custom_components/ha_power_control/switch.py` | Modify | Persist DryRun + ClimateOverride to `entry.options`. |
| `custom_components/ha_power_control/binary_sensor.py` | Modify | `OwnsClimateBinary` reads `precool_active OR peak_hold_active` from store. |
| `custom_components/ha_power_control/number.py` | Modify | Add `precool_offset_f` slider. |
| `custom_components/ha_power_control/manifest.json` | Modify | Bump version to `0.2.0`. |
| `tests/test_policy_climate.py` | Create | Unit tests for `decide()`. |
| `tests/test_climate_runner.py` | Create | Tests for runner with dry-run gate. |
| `tests/test_climate_persistence.py` | Create | Restart-recovery integration tests. |
| `tests/test_climate_e2e.py` | Create | Coordinator-driven end-to-end cycle. |
| `tests/test_switch.py` | Modify (or create if absent) | Verify DryRun/ClimateOverride persist to entry.options. |
| `README.md` | Modify | P2 entry in roadmap, climate-control usage section. |

---

## Task 1: Persist DryRun + ClimateOverride switches to `entry.options`

**Why first:** P1 stored these in-memory. The policy must read them deterministically from one place. Without this, a HA restart silently flips dry-run back to default and the policy decisions disagree with what the user sees in the UI.

**Files:**
- Modify: `custom_components/ha_power_control/switch.py:70-111` (DryRunSwitch + ClimateOverrideSwitch)
- Test: `tests/test_switch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_switch.py`:

```python
"""Switch persistence tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_power_control.const import (
    CONF_CLIMATE,
    CONF_INDOOR_TEMPS,
    CONF_NET_EXPORT_KWH,
    CONF_NET_IMPORT_KWH,
    CONF_NET_W,
    CONF_NET_W_SIGN,
    DOMAIN,
)


def _entry_data() -> dict:
    return {
        CONF_NET_W: "sensor.eagle_200_meter_power_demand",
        CONF_NET_IMPORT_KWH: "sensor.eagle_200_total_meter_energy_delivered",
        CONF_NET_EXPORT_KWH: "sensor.eagle_200_total_meter_energy_received",
        CONF_CLIMATE: "climate.thermostat",
        CONF_INDOOR_TEMPS: ["sensor.bedroom_temperature"],
        CONF_NET_W_SIGN: 1,
    }


def _seed_min_states(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand", "0",
        {"unit_of_measurement": "kW", "device_class": "power"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_delivered", "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_received", "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "climate.thermostat", "heat_cool",
        {"target_temp_high": 76.0, "target_temp_low": 68.0,
         "current_temperature": 72.0, "preset_mode": "home"},
    )
    hass.states.async_set(
        "sensor.bedroom_temperature", "72.0",
        {"unit_of_measurement": "°F"},
    )


async def test_dry_run_switch_persists_to_options(hass: HomeAssistant) -> None:
    _seed_min_states(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data(), options={"dry_run": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_off",
        {"entity_id": "switch.dry_run"}, blocking=True,
    )
    assert hass.config_entries.async_get_entry(entry.entry_id).options["dry_run"] is False


async def test_climate_override_switch_persists_to_options(hass: HomeAssistant) -> None:
    _seed_min_states(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, data=_entry_data(),
        options={"climate_override_enabled": False},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_on",
        {"entity_id": "switch.climate_override_enabled"}, blocking=True,
    )
    assert hass.config_entries.async_get_entry(
        entry.entry_id
    ).options["climate_override_enabled"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_switch.py -v`
Expected: FAIL — current switches don't persist to options.

- [ ] **Step 3: Modify `DryRunSwitch` and `ClimateOverrideSwitch`**

Replace lines 70-111 in `switch.py` with:

```python
class _PersistedFlagSwitch(_Base):
    """Boolean switch whose state is persisted in entry.options[key]."""

    _option_key: str
    _default: bool

    def __init__(self, coord: HAPowerControlCoordinator, key: str, name: str, default: bool) -> None:
        super().__init__(coord)
        self._option_key = key
        self._default = default
        self._attr_unique_id = f"{coord.entry.entry_id}_{key}"
        self._attr_name = name

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.entry.options.get(self._option_key, self._default))

    async def _persist(self, value: bool) -> None:
        new_options = {**self.coordinator.entry.options, self._option_key: value}
        self.hass.config_entries.async_update_entry(
            self.coordinator.entry, options=new_options
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._persist(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._persist(False)


class DryRunSwitch(_PersistedFlagSwitch):
    def __init__(self, coord: HAPowerControlCoordinator) -> None:
        super().__init__(coord, "dry_run", "Dry Run", DEFAULTS["dry_run"])


class ClimateOverrideSwitch(_PersistedFlagSwitch):
    """Master enable for climate writes. Default OFF."""

    def __init__(self, coord: HAPowerControlCoordinator) -> None:
        super().__init__(
            coord, "climate_override_enabled", "Climate Override Enabled",
            DEFAULTS["climate_override_enabled"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_switch.py -v`
Expected: PASS — both switches now reflect entry.options.

- [ ] **Step 5: Run full suite to verify no regression**

Run: `pytest -q`
Expected: All previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/ha_power_control/switch.py tests/test_switch.py
git commit -m "refactor(switch): persist dry_run + climate_override to entry.options"
```

---

## Task 2: Add sustained-export tracker to coordinator

**Why:** Spec §6.2 Phase-1 gate requires `export_w ≥ charge_threshold_w` for ≥10 min. The coordinator owns the timer (single source). Reset whenever export drops below threshold.

**Files:**
- Modify: `custom_components/ha_power_control/coordinator.py`
- Modify: `custom_components/ha_power_control/models.py` (add `export_run_seconds`)
- Test: `tests/test_coordinator.py` (extend)

- [ ] **Step 1: Add field to PowerState**

Edit `models.py:32-46` — add `export_run_seconds: float` after `export_w`:

```python
@dataclass(frozen=True)
class PowerState:
    ts: datetime
    net_w: float
    export_w: float
    export_run_seconds: float  # NEW: seconds export has been ≥ charge_threshold_w
    solar_w: float | None
    battery: BatteryState | None
    climate: ClimateState
    indoor_temps: dict[str, float | None]
    mean_indoor_f: float | None
    in_peak_window: bool
    tou_period: Literal["peak", "off_peak"]
    today_kwh_imported: float
    today_kwh_exported: float
    today_peak_savings_usd: float
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_coordinator.py`:

```python
async def test_coordinator_tracks_export_run_seconds(hass: HomeAssistant) -> None:
    _seed_states(hass, net_w_kw=-1.0)  # 1kW export
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    em = build_entity_map(entry.data)
    store = HAPowerControlStore(hass)
    await store.async_load()
    coord = HAPowerControlCoordinator(hass, entry, em, store)
    s1 = await coord._async_update_data()
    assert s1.export_run_seconds == 0.0
    # Same export sustained — accumulator advances
    s2 = await coord._async_update_data()
    assert s2.export_run_seconds > 0.0


async def test_coordinator_resets_export_run_when_below_threshold(
    hass: HomeAssistant,
) -> None:
    _seed_states(hass, net_w_kw=-1.0)
    entry = MockConfigEntry(domain=DOMAIN, data=_entry_data())
    entry.add_to_hass(hass)
    em = build_entity_map(entry.data)
    store = HAPowerControlStore(hass)
    await store.async_load()
    coord = HAPowerControlCoordinator(hass, entry, em, store)
    await coord._async_update_data()
    # Export collapses
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand", "0.5",
        {"unit_of_measurement": "kW", "device_class": "power"},
    )
    s = await coord._async_update_data()
    assert s.export_run_seconds == 0.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_coordinator.py::test_coordinator_tracks_export_run_seconds -v`
Expected: FAIL — `export_run_seconds` does not exist yet.

- [ ] **Step 4: Implement the tracker in coordinator**

In `coordinator.py`, add to `__init__` (after the `included_indoor_temps` loop):

```python
        # Sustained-export tracker for precool gate (spec §6.2 Phase 1)
        self._export_run_started: datetime | None = None
```

Replace the `_async_update_data` method's body (rewrite the relevant portion):

After computing `export_w` and `solar_w`, but before assembling the rest, add:

```python
        # Spec §6.2: track sustained export ≥ charge_threshold_w
        threshold = float(
            self.entry.options.get("charge_threshold_w", 200.0)
        )
        if export_w >= threshold:
            if self._export_run_started is None:
                self._export_run_started = ts
            export_run_seconds = (ts - self._export_run_started).total_seconds()
        else:
            self._export_run_started = None
            export_run_seconds = 0.0
```

Pass `export_run_seconds=export_run_seconds` into the `PowerState(...)` constructor.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_coordinator.py -v`
Expected: PASS.

- [ ] **Step 6: Run full suite — confirm no regression**

Run: `pytest -q`
Expected: All previous tests still pass (including any that construct `PowerState` directly).

If any failures arise from constructing `PowerState` without `export_run_seconds`, add `export_run_seconds=0.0` at those construction sites.

- [ ] **Step 7: Commit**

```bash
git add custom_components/ha_power_control/coordinator.py custom_components/ha_power_control/models.py tests/test_coordinator.py
git commit -m "feat(coordinator): track sustained-export run seconds for precool gate"
```

---

## Task 3: Climate state persistence schema in Store

**Why:** All policy state (`captured_originals`, active flags, `last_write_record`, `cooldown_until`) must survive HA restart. Spec §6.2 mandates restart-recovery test.

**Files:**
- Modify: `custom_components/ha_power_control/store.py`
- Test: `tests/test_climate_persistence.py` (create — partial; expanded later)

- [ ] **Step 1: Write the failing test**

Create `tests/test_climate_persistence.py`:

```python
"""Tests for ClimateState persistence in HAPowerControlStore."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.ha_power_control.store import HAPowerControlStore


async def test_get_climate_state_returns_defaults_when_empty(
    hass: HomeAssistant,
) -> None:
    store = HAPowerControlStore(hass)
    await store.async_load()
    cs = store.get_climate_state()
    assert cs == {
        "captured_originals": None,
        "precool_active": False,
        "peak_hold_active": False,
        "precool_ran_this_cycle": False,
        "last_write_record": None,
        "cooldown_until": None,
    }


async def test_set_and_get_climate_state_round_trips(hass: HomeAssistant) -> None:
    store = HAPowerControlStore(hass)
    await store.async_load()
    payload = {
        "captured_originals": {
            "target_high_f": 76.0,
            "target_low_f": 68.0,
            "preset": "home",
            "captured_at": "2026-05-06T15:00:00+00:00",
        },
        "precool_active": True,
        "peak_hold_active": False,
        "precool_ran_this_cycle": True,
        "last_write_record": {
            "target_high": 72.0,
            "preset": "home",
            "written_at": "2026-05-06T15:00:30+00:00",
        },
        "cooldown_until": None,
    }
    await store.set_climate_state(payload)
    assert store.get_climate_state() == payload

    # Round-trip across a fresh load
    store2 = HAPowerControlStore(hass)
    await store2.async_load()
    assert store2.get_climate_state() == payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_climate_persistence.py -v`
Expected: FAIL — `get_climate_state`/`set_climate_state` not defined.

- [ ] **Step 3: Implement schema helpers**

Replace `store.py` with:

```python
"""Persistence wrapper for HA Power Control."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORE_KEY, STORE_VERSION

_CLIMATE_DEFAULTS: dict[str, Any] = {
    "captured_originals": None,
    "precool_active": False,
    "peak_hold_active": False,
    "precool_ran_this_cycle": False,
    "last_write_record": None,
    "cooldown_until": None,
}


class HAPowerControlStore:
    """Lightweight wrapper around HA Store for cross-restart persistence."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store = Store(hass, STORE_VERSION, STORE_KEY)
        self._cache: dict[str, Any] = {}

    async def async_load(self) -> dict[str, Any]:
        data = await self._store.async_load() or {}
        self._cache = data
        return data

    async def async_save(self, data: dict[str, Any]) -> None:
        self._cache = data
        await self._store.async_save(data)

    @property
    def cache(self) -> dict[str, Any]:
        return self._cache

    # --- Climate state helpers (spec §6.2) ---

    def get_climate_state(self) -> dict[str, Any]:
        """Return persisted climate state with defaults filled in."""
        cs = dict(_CLIMATE_DEFAULTS)
        cs.update(self._cache.get("climate", {}))
        return cs

    async def set_climate_state(self, climate_state: dict[str, Any]) -> None:
        """Persist climate state under the 'climate' subkey."""
        new_cache = {**self._cache, "climate": dict(climate_state)}
        await self.async_save(new_cache)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_climate_persistence.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/ha_power_control/store.py tests/test_climate_persistence.py
git commit -m "feat(store): climate-state schema helpers (captured_originals, flags, cooldown)"
```

---

## Task 4: Pure-policy types + idle-case `decide()`

**Why:** Establish data contracts and a no-op default before adding behavior. Each subsequent task adds one branch with its own test, TDD-style.

**Files:**
- Create: `custom_components/ha_power_control/policy/__init__.py`
- Create: `custom_components/ha_power_control/policy/climate.py`
- Test: `tests/test_policy_climate.py`

- [ ] **Step 1: Create package marker**

Create `custom_components/ha_power_control/policy/__init__.py`:

```python
"""Pure-Python policy modules. No HA imports here."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_policy_climate.py`:

```python
"""Unit tests for the climate-controller decide() function."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from custom_components.ha_power_control.policy.climate import (
    Action,
    ActionKind,
    ClimateInputs,
    decide,
)


def _now() -> datetime:
    return datetime(2026, 5, 6, 14, 0, 0, tzinfo=timezone.utc)


def _persisted_empty() -> dict[str, Any]:
    return {
        "captured_originals": None,
        "precool_active": False,
        "peak_hold_active": False,
        "precool_ran_this_cycle": False,
        "last_write_record": None,
        "cooldown_until": None,
    }


def _options_default() -> dict[str, Any]:
    return {
        "dry_run": False,
        "climate_override_enabled": True,
        "precool_offset_f": 4.0,
        "peak_max_temp_f": 80.0,
        "min_cool_f": 65.0,
        "max_cool_f": 82.0,
        "charge_threshold_w": 200.0,
        "drift_tolerance_f": 0.5,
        "drift_grace_s": 60,
        "cooldown_min": 30,
        "sleep_start_h": 22,
        "sleep_end_h": 6,
        "precool_lead_min": 60,
    }


def _inputs(**overrides) -> ClimateInputs:
    base = dict(
        ts=_now(),
        export_w=0.0,
        export_run_seconds=0.0,
        mean_indoor_f=72.0,
        climate_current_f=72.0,
        climate_target_high_f=76.0,
        climate_target_low_f=68.0,
        climate_preset="home",
        climate_hvac_mode="heat_cool",
        in_peak_window=False,
        seconds_until_peak_start=86400,
        persisted=_persisted_empty(),
        options=_options_default(),
    )
    base.update(overrides)
    return ClimateInputs(**base)


def test_decide_idle_returns_noop_when_nothing_to_do() -> None:
    out = decide(_inputs())
    assert out.kind == ActionKind.NOOP
    assert out.next_persisted == _persisted_empty()


def test_decide_noop_when_climate_override_disabled() -> None:
    opts = _options_default()
    opts["climate_override_enabled"] = False
    out = decide(_inputs(options=opts))
    assert out.kind == ActionKind.NOOP


def test_decide_noop_when_climate_unhealthy() -> None:
    out = decide(_inputs(climate_hvac_mode="cool"))  # not heat_cool
    assert out.kind == ActionKind.NOOP
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_policy_climate.py -v`
Expected: FAIL — `policy.climate` does not exist.

- [ ] **Step 4: Implement minimal `decide()`**

Create `custom_components/ha_power_control/policy/climate.py`:

```python
"""Pure-Python climate policy. No HA imports.

Spec: docs/superpowers/specs/2026-05-03-ha-power-control-design.md §6.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ActionKind(str, Enum):
    NOOP = "noop"
    PRECOOL_START = "precool_start"
    PEAK_HOLD_START = "peak_hold_start"
    RESTORE = "restore"
    SET_COOLDOWN = "set_cooldown"


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    target_high_f: float | None = None
    preset: str | None = None
    next_persisted: dict[str, Any] = field(default_factory=dict)
    log_reason: str = ""


@dataclass(frozen=True)
class ClimateInputs:
    ts: datetime
    export_w: float
    export_run_seconds: float
    mean_indoor_f: float | None
    climate_current_f: float | None
    climate_target_high_f: float | None
    climate_target_low_f: float | None
    climate_preset: str | None
    climate_hvac_mode: str | None
    in_peak_window: bool
    seconds_until_peak_start: int
    persisted: dict[str, Any]
    options: dict[str, Any]


def _is_healthy(inp: ClimateInputs) -> bool:
    return (
        inp.climate_hvac_mode == "heat_cool"
        and inp.climate_target_high_f is not None
        and inp.climate_target_low_f is not None
    )


def _in_sleep_window(ts: datetime, start_h: int, end_h: int) -> bool:
    h = ts.hour
    if start_h <= end_h:
        return start_h <= h < end_h
    return h >= start_h or h < end_h


def decide(inp: ClimateInputs) -> Action:
    """Return the Action the runner should execute this tick."""
    persisted = dict(inp.persisted)

    if not inp.options.get("climate_override_enabled", False):
        return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="override_disabled")

    if not _is_healthy(inp):
        return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="climate_unhealthy")

    return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="idle")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_policy_climate.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/ha_power_control/policy/__init__.py custom_components/ha_power_control/policy/climate.py tests/test_policy_climate.py
git commit -m "feat(policy): scaffold climate policy with idle/no-op decide()"
```

---

## Task 5: `decide()` precool entry branch

**Why:** First active behavior. All five gates from spec §6.2 Phase 1 must be true (sustained export, time_to_peak window, indoor temp warm enough, not sleeping, not in cooldown). Capture originals atomically with the write decision.

**Files:**
- Modify: `custom_components/ha_power_control/policy/climate.py`
- Modify: `tests/test_policy_climate.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_policy_climate.py`:

```python
def test_precool_starts_when_all_gates_pass() -> None:
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,        # > 10 min
        mean_indoor_f=78.0,              # warm enough
        seconds_until_peak_start=30 * 60,  # 30 min until peak (within precool_lead_min=60)
    )
    out = decide(inp)
    assert out.kind == ActionKind.PRECOOL_START
    assert out.target_high_f == 76.0 - 4.0  # captured.target_high - precool_offset
    assert out.next_persisted["precool_active"] is True
    assert out.next_persisted["precool_ran_this_cycle"] is True
    assert out.next_persisted["captured_originals"] == {
        "target_high_f": 76.0,
        "target_low_f": 68.0,
        "preset": "home",
        "captured_at": _now().isoformat(),
    }


def test_precool_skipped_when_export_run_too_short() -> None:
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=300.0,   # only 5 min — fails ≥10 min gate
        mean_indoor_f=78.0,
        seconds_until_peak_start=30 * 60,
    )
    assert decide(inp).kind == ActionKind.NOOP


def test_precool_skipped_when_too_early_for_peak() -> None:
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=78.0,
        seconds_until_peak_start=4 * 60 * 60,  # 4h out — outside 60-min window
    )
    assert decide(inp).kind == ActionKind.NOOP


def test_precool_skipped_when_indoor_already_cool() -> None:
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=70.0,  # below peak_max_temp_f − precool_offset = 76
        seconds_until_peak_start=30 * 60,
    )
    assert decide(inp).kind == ActionKind.NOOP


def test_precool_skipped_during_sleep_window() -> None:
    sleep_ts = datetime(2026, 5, 6, 23, 0, 0, tzinfo=timezone.utc)
    inp = _inputs(
        ts=sleep_ts,
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=78.0,
        seconds_until_peak_start=30 * 60,
    )
    assert decide(inp).kind == ActionKind.NOOP


def test_precool_skipped_when_dry_run_on() -> None:
    opts = _options_default()
    opts["dry_run"] = True
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=78.0,
        seconds_until_peak_start=30 * 60,
        options=opts,
    )
    # Dry-run is enforced by the runner, not the policy. Policy still emits the
    # action; runner is responsible for the gate. This test pins that contract.
    assert decide(inp).kind == ActionKind.PRECOOL_START
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_policy_climate.py -v`
Expected: 5 of 6 new tests fail (`PRECOOL_START` never returned by current `decide()`).

- [ ] **Step 3: Add precool branch to `decide()`**

In `policy/climate.py`, add a helper and extend `decide()`:

```python
def _precool_gates_pass(inp: ClimateInputs) -> bool:
    o = inp.options
    p = inp.persisted

    if p.get("precool_active") or p.get("peak_hold_active"):
        return False  # already in cycle
    if inp.in_peak_window:
        return False  # too late
    if inp.export_w < o["charge_threshold_w"]:
        return False
    if inp.export_run_seconds < 600:  # 10 min
        return False
    lead_s = o["precool_lead_min"] * 60
    if not (0 < inp.seconds_until_peak_start <= lead_s):
        return False
    if inp.mean_indoor_f is None:
        return False
    if inp.mean_indoor_f <= o["peak_max_temp_f"] - o["precool_offset_f"]:
        return False
    if _in_sleep_window(inp.ts, o["sleep_start_h"], o["sleep_end_h"]):
        return False
    return True
```

Replace the trailing `return Action(kind=ActionKind.NOOP, ..., log_reason="idle")` line in `decide()` with:

```python
    if _precool_gates_pass(inp):
        captured = {
            "target_high_f": inp.climate_target_high_f,
            "target_low_f": inp.climate_target_low_f,
            "preset": inp.climate_preset,
            "captured_at": inp.ts.isoformat(),
        }
        new_high = inp.climate_target_high_f - inp.options["precool_offset_f"]
        persisted["captured_originals"] = captured
        persisted["precool_active"] = True
        persisted["precool_ran_this_cycle"] = True
        return Action(
            kind=ActionKind.PRECOOL_START,
            target_high_f=new_high,
            next_persisted=persisted,
            log_reason="precool_gates_passed",
        )

    return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="idle")
```

- [ ] **Step 4: Run tests — expect pass**

Run: `pytest tests/test_policy_climate.py -v`
Expected: PASS for all precool-branch tests.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/ha_power_control/policy/climate.py tests/test_policy_climate.py
git commit -m "feat(policy): precool entry branch with full §6.2 gate set"
```

---

## Task 6: `decide()` peak-hold transition (Phase 1 → 2)

**Why:** At peak start, switch from `target_high − precool_offset` to `peak_max_temp_f` without restoring originals. Spec: peak-hold may not enter if `precool_ran_this_cycle` is false.

**Files:**
- Modify: `custom_components/ha_power_control/policy/climate.py`
- Modify: `tests/test_policy_climate.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_policy_climate.py`:

```python
def test_peak_hold_starts_at_peak_when_precool_was_active() -> None:
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    inp = _inputs(
        in_peak_window=True,
        seconds_until_peak_start=0,
        climate_target_high_f=72.0,  # currently in precool
        persisted=persisted,
    )
    out = decide(inp)
    assert out.kind == ActionKind.PEAK_HOLD_START
    assert out.target_high_f == 80.0  # peak_max_temp_f
    assert out.next_persisted["precool_active"] is False
    assert out.next_persisted["peak_hold_active"] is True
    # captured_originals MUST be preserved across the transition
    assert out.next_persisted["captured_originals"] == persisted["captured_originals"]


def test_peak_hold_does_not_enter_without_precool_ran_this_cycle() -> None:
    """Cold-start mid-peak: persisted says peak_hold_active but no precool ran."""
    persisted = _persisted_empty()
    persisted["peak_hold_active"] = True
    persisted["precool_ran_this_cycle"] = False  # corrupt / cold start
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    inp = _inputs(in_peak_window=True, seconds_until_peak_start=0, persisted=persisted)
    out = decide(inp)
    # Spec §6.2: abandon cycle, restore originals.
    assert out.kind == ActionKind.RESTORE
    assert out.next_persisted["peak_hold_active"] is False
    assert out.next_persisted["precool_ran_this_cycle"] is False
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_policy_climate.py::test_peak_hold_starts_at_peak_when_precool_was_active -v`
Expected: FAIL.

- [ ] **Step 3: Add peak-hold branch**

In `policy/climate.py`, before the `_precool_gates_pass(inp)` check inside `decide()`, insert:

```python
    # Peak-hold transition / corrupt-state recovery
    if inp.in_peak_window and persisted.get("peak_hold_active"):
        # Already in peak hold from a prior tick — handled by RESTORE branch
        # at peak end (Task 7). Hold steady this tick.
        return Action(
            kind=ActionKind.NOOP,
            next_persisted=persisted,
            log_reason="peak_hold_steady",
        )

    if inp.in_peak_window and persisted.get("precool_active"):
        if not persisted.get("precool_ran_this_cycle"):
            # Should not occur (precool_active implies precool_ran), but be defensive.
            persisted["precool_active"] = False
            persisted["peak_hold_active"] = False
            return Action(
                kind=ActionKind.RESTORE,
                target_high_f=persisted["captured_originals"]["target_high_f"],
                preset=persisted["captured_originals"]["preset"],
                next_persisted=persisted,
                log_reason="abandon_partial_cycle",
            )
        persisted["precool_active"] = False
        persisted["peak_hold_active"] = True
        return Action(
            kind=ActionKind.PEAK_HOLD_START,
            target_high_f=inp.options["peak_max_temp_f"],
            next_persisted=persisted,
            log_reason="peak_hold_entry",
        )

    if (
        inp.in_peak_window
        and persisted.get("captured_originals")
        and not persisted.get("precool_ran_this_cycle")
    ):
        # Cold-start mid-peak with stale captured_originals — abandon and restore.
        originals = persisted["captured_originals"]
        persisted["peak_hold_active"] = False
        persisted["precool_active"] = False
        return Action(
            kind=ActionKind.RESTORE,
            target_high_f=originals["target_high_f"],
            preset=originals["preset"],
            next_persisted=persisted,
            log_reason="cold_start_abandon",
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_policy_climate.py -v`
Expected: PASS for new tests; existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ha_power_control/policy/climate.py tests/test_policy_climate.py
git commit -m "feat(policy): peak-hold Phase-2 transition + cold-start abandonment"
```

---

## Task 7: `decide()` restoration on peak-window falling edge

**Why:** Spec §6.2 — at 8:00pm restore captured originals exactly. Also: if precool conditions cease before peak (export collapses, sleep starts), restore immediately and skip Phase 2.

**Files:**
- Modify: `custom_components/ha_power_control/policy/climate.py`
- Modify: `tests/test_policy_climate.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_policy_climate.py`:

```python
def test_restore_at_peak_window_falling_edge() -> None:
    persisted = _persisted_empty()
    persisted["peak_hold_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    # Peak just ended
    inp = _inputs(in_peak_window=False, persisted=persisted)
    out = decide(inp)
    assert out.kind == ActionKind.RESTORE
    assert out.target_high_f == 76.0
    assert out.preset == "home"
    assert out.next_persisted["peak_hold_active"] is False
    assert out.next_persisted["precool_active"] is False
    assert out.next_persisted["precool_ran_this_cycle"] is False
    assert out.next_persisted["captured_originals"] is None


def test_precool_aborts_when_export_collapses_before_peak() -> None:
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    inp = _inputs(
        export_w=0.0,  # collapsed
        export_run_seconds=0.0,
        in_peak_window=False,
        seconds_until_peak_start=20 * 60,
        persisted=persisted,
    )
    out = decide(inp)
    assert out.kind == ActionKind.RESTORE
    assert out.target_high_f == 76.0
    assert out.next_persisted["precool_active"] is False


def test_precool_aborts_when_sleep_window_starts() -> None:
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    sleep_ts = datetime(2026, 5, 6, 23, 0, 0, tzinfo=timezone.utc)
    inp = _inputs(
        ts=sleep_ts,
        export_w=300.0,
        export_run_seconds=700.0,
        in_peak_window=False,
        persisted=persisted,
    )
    out = decide(inp)
    assert out.kind == ActionKind.RESTORE
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_policy_climate.py -v`
Expected: FAIL on the three new restore tests.

- [ ] **Step 3: Add restore branches**

In `policy/climate.py`, before the peak-hold transition block (Task 6), insert this restore handling block. Place it after the health/override gates but before any peak-hold logic:

```python
    captured = persisted.get("captured_originals")

    # Falling edge of peak window: restore originals
    if persisted.get("peak_hold_active") and not inp.in_peak_window and captured:
        persisted["peak_hold_active"] = False
        persisted["precool_active"] = False
        persisted["precool_ran_this_cycle"] = False
        persisted["captured_originals"] = None
        return Action(
            kind=ActionKind.RESTORE,
            target_high_f=captured["target_high_f"],
            preset=captured["preset"],
            next_persisted=persisted,
            log_reason="peak_window_ended",
        )

    # Precool active but conditions ceased before peak start
    if persisted.get("precool_active") and not inp.in_peak_window and captured:
        export_ok = inp.export_run_seconds >= 600 and inp.export_w >= inp.options["charge_threshold_w"]
        sleeping = _in_sleep_window(inp.ts, inp.options["sleep_start_h"], inp.options["sleep_end_h"])
        if (not export_ok) or sleeping:
            persisted["precool_active"] = False
            persisted["precool_ran_this_cycle"] = False
            persisted["captured_originals"] = None
            return Action(
                kind=ActionKind.RESTORE,
                target_high_f=captured["target_high_f"],
                preset=captured["preset"],
                next_persisted=persisted,
                log_reason="precool_aborted",
            )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_policy_climate.py -v`
Expected: PASS for all restore tests; prior tests still pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ha_power_control/policy/climate.py tests/test_policy_climate.py
git commit -m "feat(policy): restoration on peak end + precool abort paths"
```

---

## Task 8: Hard-exits during peak-hold

**Why:** Spec §6.2 — if `mean_indoor_f > peak_max_temp_f` during peak hold, abort hold and restore (allow AC). This protects comfort.

**Files:**
- Modify: `custom_components/ha_power_control/policy/climate.py`
- Modify: `tests/test_policy_climate.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_policy_climate.py`:

```python
def test_peak_hold_aborts_when_indoor_exceeds_ceiling() -> None:
    persisted = _persisted_empty()
    persisted["peak_hold_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    inp = _inputs(
        in_peak_window=True,
        mean_indoor_f=82.0,  # above peak_max_temp_f=80
        persisted=persisted,
    )
    out = decide(inp)
    assert out.kind == ActionKind.RESTORE
    assert out.target_high_f == 76.0
    assert out.next_persisted["peak_hold_active"] is False
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/test_policy_climate.py::test_peak_hold_aborts_when_indoor_exceeds_ceiling -v`
Expected: FAIL — current code returns NOOP "peak_hold_steady".

- [ ] **Step 3: Insert hard-exit check in peak-hold-steady branch**

In `policy/climate.py`, replace the existing `peak_hold_steady` branch:

```python
    if inp.in_peak_window and persisted.get("peak_hold_active"):
        if (
            inp.mean_indoor_f is not None
            and inp.mean_indoor_f > inp.options["peak_max_temp_f"]
            and captured is not None
        ):
            persisted["peak_hold_active"] = False
            persisted["precool_active"] = False
            persisted["precool_ran_this_cycle"] = False
            persisted["captured_originals"] = None
            return Action(
                kind=ActionKind.RESTORE,
                target_high_f=captured["target_high_f"],
                preset=captured["preset"],
                next_persisted=persisted,
                log_reason="hard_exit_temp_above_ceiling",
            )
        return Action(
            kind=ActionKind.NOOP,
            next_persisted=persisted,
            log_reason="peak_hold_steady",
        )
```

(Note: `captured` is defined earlier in `decide()` per Task 7.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_policy_climate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ha_power_control/policy/climate.py tests/test_policy_climate.py
git commit -m "feat(policy): hard-exit peak hold when mean indoor temp exceeds ceiling"
```

---

## Task 9: External-override detection + cooldown

**Why:** Spec §6.2 — if user touches Ecobee, stop writing. Drift = `|current_high − written_high| > drift_tolerance` OR `current.preset != written.preset`, evaluated only after `drift_grace_s` since last write. On drift → start cooldown of `cooldown_min`. While in cooldown, `decide()` returns NOOP.

**Files:**
- Modify: `custom_components/ha_power_control/policy/climate.py`
- Modify: `tests/test_policy_climate.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_policy_climate.py`:

```python
from datetime import timedelta


def test_drift_detected_starts_cooldown() -> None:
    written_at = _now() - timedelta(seconds=120)  # outside grace
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    persisted["last_write_record"] = {
        "target_high": 72.0,  # we wrote 72
        "preset": "home",
        "written_at": written_at.isoformat(),
    }
    # User has bumped thermostat to 74 — drift > 0.5°F
    inp = _inputs(climate_target_high_f=74.0, persisted=persisted)
    out = decide(inp)
    assert out.kind == ActionKind.SET_COOLDOWN
    assert out.next_persisted["cooldown_until"] is not None
    # No write follows; precool stays active in persisted but writes suppressed.


def test_drift_within_grace_does_not_trigger() -> None:
    written_at = _now() - timedelta(seconds=30)  # inside drift_grace_s=60
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    persisted["last_write_record"] = {
        "target_high": 72.0,
        "preset": "home",
        "written_at": written_at.isoformat(),
    }
    # Thermostat hasn't reflected the write yet
    inp = _inputs(climate_target_high_f=76.0, persisted=persisted)
    out = decide(inp)
    assert out.kind != ActionKind.SET_COOLDOWN


def test_cooldown_suppresses_actions() -> None:
    cooldown_until = _now() + timedelta(minutes=10)
    persisted = _persisted_empty()
    persisted["cooldown_until"] = cooldown_until.isoformat()
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=78.0,
        seconds_until_peak_start=30 * 60,
        persisted=persisted,
    )
    assert decide(inp).kind == ActionKind.NOOP
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_policy_climate.py -v`
Expected: FAIL on the three new tests.

- [ ] **Step 3: Add drift + cooldown logic**

In `policy/climate.py`, add these helpers near the top:

```python
def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _drift_detected(inp: ClimateInputs) -> bool:
    rec = inp.persisted.get("last_write_record")
    if not rec:
        return False
    written_at = _parse_iso(rec.get("written_at"))
    if written_at is None:
        return False
    grace_s = inp.options["drift_grace_s"]
    if (inp.ts - written_at).total_seconds() < grace_s:
        return False
    tol = inp.options["drift_tolerance_f"]
    high_drift = (
        inp.climate_target_high_f is not None
        and abs(inp.climate_target_high_f - rec["target_high"]) > tol
    )
    preset_drift = inp.climate_preset != rec.get("preset")
    return high_drift or preset_drift
```

In `decide()`, immediately after the health/override checks (and before any restore/precool/peak-hold logic), insert:

```python
    # Cooldown gate
    cooldown_until = _parse_iso(persisted.get("cooldown_until"))
    if cooldown_until and inp.ts < cooldown_until:
        return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="in_cooldown")
    if cooldown_until and inp.ts >= cooldown_until:
        persisted["cooldown_until"] = None  # cooldown elapsed; clear

    # External override detection — only meaningful when we have an active
    # cycle or have written recently. Avoids spurious cooldowns at idle.
    has_active_cycle_or_write = (
        persisted.get("precool_active")
        or persisted.get("peak_hold_active")
        or persisted.get("last_write_record") is not None
    )
    if has_active_cycle_or_write and _drift_detected(inp):
        cd_min = inp.options["cooldown_min"]
        persisted["cooldown_until"] = (inp.ts + timedelta(minutes=cd_min)).isoformat()
        return Action(
            kind=ActionKind.SET_COOLDOWN,
            next_persisted=persisted,
            log_reason="drift_detected",
        )
```

Add the import at the top of the file:

```python
from datetime import datetime, timedelta
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_policy_climate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ha_power_control/policy/climate.py tests/test_policy_climate.py
git commit -m "feat(policy): drift detection + cooldown for external-override safety"
```

---

## Task 10: Safety bounds clip on every emitted target_high

**Why:** Spec §7.1 invariant: every setpoint write must satisfy `min_cool_f ≤ target_high ≤ max_cool_f`. The policy is the chokepoint.

**Files:**
- Modify: `custom_components/ha_power_control/policy/climate.py`
- Modify: `tests/test_policy_climate.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_policy_climate.py`:

```python
def test_target_high_clamped_to_min_cool_f() -> None:
    """If captured original would precool below min_cool_f, clip up."""
    inp = _inputs(
        export_w=300.0,
        export_run_seconds=700.0,
        mean_indoor_f=78.0,
        seconds_until_peak_start=30 * 60,
        climate_target_high_f=68.0,  # already low; precool would yield 64°F
    )
    out = decide(inp)
    assert out.kind == ActionKind.PRECOOL_START
    assert out.target_high_f == 65.0  # min_cool_f


def test_peak_hold_target_clamped_to_max_cool_f() -> None:
    """peak_max_temp_f set above max_cool_f must clip down."""
    persisted = _persisted_empty()
    persisted["precool_active"] = True
    persisted["precool_ran_this_cycle"] = True
    persisted["captured_originals"] = {
        "target_high_f": 76.0, "target_low_f": 68.0,
        "preset": "home", "captured_at": _now().isoformat(),
    }
    opts = _options_default()
    opts["peak_max_temp_f"] = 90.0  # above max_cool_f=82
    inp = _inputs(in_peak_window=True, persisted=persisted, options=opts)
    out = decide(inp)
    assert out.kind == ActionKind.PEAK_HOLD_START
    assert out.target_high_f == 82.0  # clamped
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_policy_climate.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement clamping**

In `policy/climate.py`, add helper:

```python
def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
```

Wherever `decide()` constructs an `Action` with `target_high_f=<expr>`, wrap it with `_clamp(<expr>, opts["min_cool_f"], opts["max_cool_f"])`. This applies to the `PRECOOL_START` and `PEAK_HOLD_START` branches. (RESTORE branches use captured originals which were verified at config-flow time, but apply clamp there as well for defense-in-depth.)

For the precool branch:

```python
        new_high = _clamp(
            inp.climate_target_high_f - inp.options["precool_offset_f"],
            inp.options["min_cool_f"],
            inp.options["max_cool_f"],
        )
```

For the peak-hold-start branch:

```python
        return Action(
            kind=ActionKind.PEAK_HOLD_START,
            target_high_f=_clamp(
                inp.options["peak_max_temp_f"],
                inp.options["min_cool_f"],
                inp.options["max_cool_f"],
            ),
            next_persisted=persisted,
            log_reason="peak_hold_entry",
        )
```

For each `RESTORE` action, wrap `target_high_f=captured["target_high_f"]` in `_clamp(captured["target_high_f"], inp.options["min_cool_f"], inp.options["max_cool_f"])`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_policy_climate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ha_power_control/policy/climate.py tests/test_policy_climate.py
git commit -m "feat(policy): clamp every target_high to [min_cool_f, max_cool_f]"
```

---

## Task 11: Climate runner — service-call executor

**Why:** Bridges pure policy → HA. Honors `dry_run` here (single execution gate). Records `last_write_record` after every successful write.

**Files:**
- Create: `custom_components/ha_power_control/policy/climate_runner.py`
- Test: `tests/test_climate_runner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_climate_runner.py`:

```python
"""Tests for ClimateRunner service-call execution + dry-run gate."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.ha_power_control.policy.climate import Action, ActionKind
from custom_components.ha_power_control.policy.climate_runner import ClimateRunner


def _ts() -> datetime:
    return datetime(2026, 5, 6, 14, 0, 0, tzinfo=timezone.utc)


async def test_runner_dry_run_does_not_call_service(hass: HomeAssistant) -> None:
    save_mock = AsyncMock()
    runner = ClimateRunner(
        hass,
        climate_entity="climate.thermostat",
        save_climate_state=save_mock,
        dry_run_getter=lambda: True,
    )
    action = Action(
        kind=ActionKind.PRECOOL_START,
        target_high_f=72.0,
        next_persisted={"precool_active": True},
    )
    calls: list[Any] = []
    hass.services.async_register("climate", "set_temperature", lambda call: calls.append(call))
    await runner.apply(action, _ts(), current_target_low_f=68.0)
    assert calls == []
    save_mock.assert_awaited_once()  # state still persists


async def test_runner_writes_setpoint_when_not_dry_run(hass: HomeAssistant) -> None:
    save_mock = AsyncMock()
    runner = ClimateRunner(
        hass,
        climate_entity="climate.thermostat",
        save_climate_state=save_mock,
        dry_run_getter=lambda: False,
    )
    action = Action(
        kind=ActionKind.PRECOOL_START,
        target_high_f=72.0,
        next_persisted={
            "precool_active": True,
            "captured_originals": {
                "target_high_f": 76.0, "target_low_f": 68.0, "preset": "home",
                "captured_at": _ts().isoformat(),
            },
        },
    )
    captured: list[dict[str, Any]] = []

    async def fake_service(call):
        captured.append(dict(call.data))

    hass.services.async_register("climate", "set_temperature", fake_service)
    await runner.apply(action, _ts(), current_target_low_f=68.0)
    assert len(captured) == 1
    assert captured[0]["entity_id"] == "climate.thermostat"
    assert captured[0]["target_temp_high"] == 72.0
    assert captured[0]["target_temp_low"] == 68.0  # never touch heat threshold
    # last_write_record persisted
    save_mock.assert_awaited()
    persisted = save_mock.call_args.args[0]
    assert persisted["last_write_record"]["target_high"] == 72.0
    assert persisted["last_write_record"]["written_at"] == _ts().isoformat()


async def test_runner_noop_does_not_call_service(hass: HomeAssistant) -> None:
    save_mock = AsyncMock()
    runner = ClimateRunner(
        hass, climate_entity="climate.thermostat",
        save_climate_state=save_mock, dry_run_getter=lambda: False,
    )
    action = Action(kind=ActionKind.NOOP, next_persisted={})
    calls: list[Any] = []
    hass.services.async_register("climate", "set_temperature", lambda c: calls.append(c))
    await runner.apply(action, _ts(), current_target_low_f=68.0)
    assert calls == []
    # NOOP still persists in case the policy mutated cooldown_until or similar
    save_mock.assert_awaited_once()
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/test_climate_runner.py -v`
Expected: FAIL (`ClimateRunner` does not exist).

- [ ] **Step 3: Implement runner**

Create `custom_components/ha_power_control/policy/climate_runner.py`:

```python
"""Async runner that translates Action → HA service calls + Store writes."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from homeassistant.core import HomeAssistant

from .climate import Action, ActionKind

_LOGGER = logging.getLogger(__name__)

_WRITING_KINDS = {
    ActionKind.PRECOOL_START,
    ActionKind.PEAK_HOLD_START,
    ActionKind.RESTORE,
}


class ClimateRunner:
    """Apply policy Actions to HA, gated by dry_run."""

    def __init__(
        self,
        hass: HomeAssistant,
        climate_entity: str,
        save_climate_state: Callable[[dict[str, Any]], Awaitable[None]],
        dry_run_getter: Callable[[], bool],
    ) -> None:
        self._hass = hass
        self._climate_entity = climate_entity
        self._save = save_climate_state
        self._dry_run_getter = dry_run_getter

    async def apply(
        self,
        action: Action,
        ts: datetime,
        *,
        current_target_low_f: float | None,
    ) -> None:
        """Execute Action, persist next_persisted regardless."""
        persisted = dict(action.next_persisted)

        write_attempted = action.kind in _WRITING_KINDS and action.target_high_f is not None
        if write_attempted and not self._dry_run_getter():
            await self._write_setpoint(
                target_high_f=action.target_high_f,
                target_low_f=current_target_low_f,
            )
            persisted["last_write_record"] = {
                "target_high": action.target_high_f,
                "preset": action.preset,
                "written_at": ts.isoformat(),
            }
            _LOGGER.info(
                "climate_runner: %s target_high=%.1f reason=%s",
                action.kind.value, action.target_high_f, action.log_reason,
            )
        elif write_attempted:
            _LOGGER.info(
                "climate_runner: DRY-RUN suppressed %s target_high=%.1f reason=%s",
                action.kind.value, action.target_high_f, action.log_reason,
            )

        await self._save(persisted)

    async def _write_setpoint(
        self,
        *,
        target_high_f: float,
        target_low_f: float | None,
    ) -> None:
        """Write target_temp_high while preserving target_temp_low.

        IMPORTANT (spec §6.2): NEVER manipulate target_temp_low.
        We pass it through unchanged so HA's heat_cool service does not
        coerce a default heat threshold that might activate the furnace.

        Note: target_high_f has already been clamped to [min_cool_f, max_cool_f]
        by the policy. If the user's original setpoint was outside those bounds,
        a RESTORE will write the clamped value rather than the literal original.
        Spec §7.1 mandates this safety bound.
        """
        data: dict[str, Any] = {
            "entity_id": self._climate_entity,
            "target_temp_high": target_high_f,
        }
        if target_low_f is not None:
            data["target_temp_low"] = target_low_f
        await self._hass.services.async_call(
            "climate", "set_temperature", data, blocking=True,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_climate_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/ha_power_control/policy/climate_runner.py tests/test_climate_runner.py
git commit -m "feat(policy): climate runner with dry-run gate and last_write_record"
```

---

## Task 12: Wire runner into the coordinator tick

**Why:** Each tick: assemble PowerState → build ClimateInputs → call decide() → apply Action. Single execution path; no parallel writers.

**Files:**
- Modify: `custom_components/ha_power_control/coordinator.py`

- [ ] **Step 1: Add runner construction + per-tick call**

In `coordinator.py`, extend imports:

```python
from .policy.climate import ClimateInputs, decide
from .policy.climate_runner import ClimateRunner
from .tou import seconds_until_peak_start
```

In `__init__`, after the export-tracker init line, add:

```python
        self._runner: ClimateRunner | None = None
```

Add a method to lazy-init the runner (so `self.entity_map` is fully populated):

```python
    def _ensure_runner(self) -> ClimateRunner:
        if self._runner is None:
            self._runner = ClimateRunner(
                hass=self.hass,
                climate_entity=self.entity_map.climate_entity,
                save_climate_state=self.store.set_climate_state,
                dry_run_getter=lambda: bool(
                    self.entry.options.get("dry_run", True)
                ),
            )
        return self._runner
```

At the end of `_async_update_data()`, just before `return PowerState(...)`, capture the assembled `state` to a local variable `state = PowerState(...)`, then run:

```python
        # Climate policy tick
        try:
            inputs = ClimateInputs(
                ts=ts,
                export_w=state.export_w,
                export_run_seconds=state.export_run_seconds,
                mean_indoor_f=state.mean_indoor_f,
                climate_current_f=state.climate.current_f,
                climate_target_high_f=state.climate.target_high_f,
                climate_target_low_f=state.climate.target_low_f,
                climate_preset=state.climate.preset,
                climate_hvac_mode=state.climate.hvac_mode,
                in_peak_window=state.in_peak_window,
                seconds_until_peak_start=seconds_until_peak_start(ts),
                persisted=self.store.get_climate_state(),
                options=dict(self.entry.options),
            )
            action = decide(inputs)
            await self._ensure_runner().apply(
                action, ts, current_target_low_f=state.climate.target_low_f,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("climate policy tick failed; coordinator continues")

        return state
```

- [ ] **Step 2: Verify default options provide policy keys**

Edit `const.py` `DEFAULTS` to include keys the policy expects but were not in P1:

```python
    "precool_lead_min": 60,
```

(Other keys — `peak_max_temp_f`, `min_cool_f`, `max_cool_f`, `precool_offset_f`, `charge_threshold_w`, `drift_tolerance_f`, `drift_grace_s`, `cooldown_min`, `sleep_start_h`, `sleep_end_h` — are already present.)

In `coordinator.py` `_ensure_runner` and the `inputs = ClimateInputs(...)` block, derive options as:

```python
        options = {**DEFAULTS, **dict(self.entry.options)}
```

and pass `options=options` to `ClimateInputs(...)`.

Add `from .const import DEFAULTS` to imports if not already present.

- [ ] **Step 3: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add custom_components/ha_power_control/coordinator.py custom_components/ha_power_control/const.py
git commit -m "feat(coordinator): drive climate policy decide()+runner each tick"
```

---

## Task 13: Restore-on-startup hook

**Why:** Spec §6.2 — if `precool_active OR peak_hold_active` is true at startup, immediately restore originals before the first tick. Edge case: `peak_hold_active` true but `precool_ran_this_cycle` false → abandon, restore.

**Files:**
- Modify: `custom_components/ha_power_control/__init__.py`
- Test: `tests/test_climate_persistence.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `tests/test_climate_persistence.py`:

```python
import json
from pathlib import Path

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_power_control.const import (
    CONF_CLIMATE,
    CONF_INDOOR_TEMPS,
    CONF_NET_EXPORT_KWH,
    CONF_NET_IMPORT_KWH,
    CONF_NET_W,
    CONF_NET_W_SIGN,
    DOMAIN,
    STORE_KEY,
    STORE_VERSION,
)


def _seed_min_states(hass) -> None:
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand", "0",
        {"unit_of_measurement": "kW", "device_class": "power"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_delivered", "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_received", "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "climate.thermostat", "heat_cool",
        {"target_temp_high": 72.0, "target_temp_low": 68.0,
         "current_temperature": 73.0, "preset_mode": "home"},
    )
    hass.states.async_set(
        "sensor.bedroom_temperature", "73.0",
        {"unit_of_measurement": "°F"},
    )


async def _seed_store(hass, climate_payload: dict) -> None:
    """Pre-populate the HA Store under our domain key."""
    storage_path = Path(hass.config.config_dir) / ".storage" / STORE_KEY
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text(json.dumps({
        "version": STORE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {"climate": climate_payload},
    }))


async def test_restore_on_startup_when_peak_hold_active(hass) -> None:
    _seed_min_states(hass)
    await _seed_store(hass, {
        "captured_originals": {
            "target_high_f": 76.0, "target_low_f": 68.0,
            "preset": "home", "captured_at": "2026-05-06T15:00:00+00:00",
        },
        "precool_active": False,
        "peak_hold_active": True,
        "precool_ran_this_cycle": True,
        "last_write_record": None,
        "cooldown_until": None,
    })

    calls: list[dict] = []

    async def fake_service(call):
        calls.append(dict(call.data))

    hass.services.async_register("climate", "set_temperature", fake_service)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NET_W: "sensor.eagle_200_meter_power_demand",
            CONF_NET_IMPORT_KWH: "sensor.eagle_200_total_meter_energy_delivered",
            CONF_NET_EXPORT_KWH: "sensor.eagle_200_total_meter_energy_received",
            CONF_CLIMATE: "climate.thermostat",
            CONF_INDOOR_TEMPS: ["sensor.bedroom_temperature"],
            CONF_NET_W_SIGN: 1,
        },
        options={"dry_run": False, "climate_override_enabled": True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Restore call must have fired with original target_high_f
    assert any(c.get("target_temp_high") == 76.0 for c in calls)
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest tests/test_climate_persistence.py::test_restore_on_startup_when_peak_hold_active -v`
Expected: FAIL — restore-on-startup not yet wired.

- [ ] **Step 3: Implement startup restore**

Edit `custom_components/ha_power_control/__init__.py`:

```python
"""HA Power Control integration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DEFAULTS, DOMAIN, PLATFORMS
from .coordinator import HAPowerControlCoordinator, build_entity_map
from .policy.climate import ActionKind, ClimateInputs, decide
from .policy.climate_runner import ClimateRunner
from .store import HAPowerControlStore

_LOGGER = logging.getLogger(__name__)


async def _maybe_restore_at_startup(
    hass: HomeAssistant, entry: ConfigEntry, store: HAPowerControlStore,
    climate_entity: str,
) -> None:
    """If a precool or peak-hold cycle was active across restart, restore originals.

    Spec §6.2: 'if precool_active or peak_hold_active is true and captured_originals
    is set, immediately write originals on coordinator first-tick'.
    """
    cs = store.get_climate_state()
    captured = cs.get("captured_originals")
    if not captured:
        return
    if not (cs.get("precool_active") or cs.get("peak_hold_active")):
        return

    options = {**DEFAULTS, **dict(entry.options)}
    if not options.get("climate_override_enabled", False):
        # User has disabled override; we still clear stale flags so the
        # next cycle starts clean — but do not write to the thermostat.
        await store.set_climate_state({
            "captured_originals": None,
            "precool_active": False,
            "peak_hold_active": False,
            "precool_ran_this_cycle": False,
            "last_write_record": None,
            "cooldown_until": None,
        })
        return

    runner = ClimateRunner(
        hass=hass, climate_entity=climate_entity,
        save_climate_state=store.set_climate_state,
        dry_run_getter=lambda: bool(options.get("dry_run", True)),
    )
    from .policy.climate import Action  # local import to avoid cycle

    cleared = {
        "captured_originals": None,
        "precool_active": False,
        "peak_hold_active": False,
        "precool_ran_this_cycle": False,
        "last_write_record": None,
        "cooldown_until": None,
    }
    action = Action(
        kind=ActionKind.RESTORE,
        target_high_f=captured["target_high_f"],
        preset=captured.get("preset"),
        next_persisted=cleared,
        log_reason="startup_restore",
    )
    await runner.apply(
        action,
        datetime.now(timezone.utc),
        current_target_low_f=captured.get("target_low_f"),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    em = build_entity_map(entry.data)
    em.validate_basic()

    store = HAPowerControlStore(hass)
    await store.async_load()

    await _maybe_restore_at_startup(hass, entry, store, em.climate_entity)

    coord = HAPowerControlCoordinator(hass, entry, em, store)
    await coord.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    coord: HAPowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coord.async_request_refresh()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_climate_persistence.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/ha_power_control/__init__.py tests/test_climate_persistence.py
git commit -m "feat(init): restore captured originals at startup if cycle was active"
```

---

## Task 14: `OwnsClimateBinary` reads store flags + add `precool_offset_f` number

**Why:** §6.2 requires owns_climate to reflect controller ownership. Add `precool_offset_f` slider for runtime tuning.

**Files:**
- Modify: `custom_components/ha_power_control/binary_sensor.py`
- Modify: `custom_components/ha_power_control/number.py`
- Test: `tests/test_platforms.py` (extend) or simple targeted test

- [ ] **Step 1: Write failing test for OwnsClimate**

Append to `tests/test_climate_persistence.py`:

```python
async def test_owns_climate_binary_reflects_active_flag(hass) -> None:
    _seed_min_states(hass)
    await _seed_store(hass, {
        "captured_originals": {
            "target_high_f": 76.0, "target_low_f": 68.0,
            "preset": "home", "captured_at": "2026-05-06T15:00:00+00:00",
        },
        "precool_active": True,
        "peak_hold_active": False,
        "precool_ran_this_cycle": True,
        "last_write_record": None,
        "cooldown_until": None,
    })
    # Don't restore-on-startup: dry_run blocks the write but flags persist.
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NET_W: "sensor.eagle_200_meter_power_demand",
            CONF_NET_IMPORT_KWH: "sensor.eagle_200_total_meter_energy_delivered",
            CONF_NET_EXPORT_KWH: "sensor.eagle_200_total_meter_energy_received",
            CONF_CLIMATE: "climate.thermostat",
            CONF_INDOOR_TEMPS: ["sensor.bedroom_temperature"],
            CONF_NET_W_SIGN: 1,
        },
        options={"dry_run": True, "climate_override_enabled": True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The startup-restore path will clear flags even in dry-run. To exercise
    # OwnsClimate we set the flag back after setup.
    coord = hass.data[DOMAIN][entry.entry_id]
    await coord.store.set_climate_state({
        "captured_originals": None, "precool_active": True, "peak_hold_active": False,
        "precool_ran_this_cycle": True, "last_write_record": None, "cooldown_until": None,
    })
    await coord.async_request_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.owns_climate")
    assert state is not None
    assert state.state == "on"
```

- [ ] **Step 2: Update OwnsClimateBinary**

Edit `binary_sensor.py:66-74`:

```python
class OwnsClimateBinary(_Base):
    """On when controller has captured originals or has an active cycle."""

    def __init__(self, c: HAPowerControlCoordinator) -> None:
        super().__init__(c, "owns_climate", "Owns Climate")

    @property
    def is_on(self) -> bool:
        cs = self.coordinator.store.get_climate_state()
        return bool(cs.get("precool_active") or cs.get("peak_hold_active"))
```

- [ ] **Step 3: Add `precool_offset_f` to number platform**

Edit `number.py:15-21`:

```python
_NUMBERS = [
    ("trueup_month", "True-Up Month", 1, 12, 1, None, NumberMode.SLIDER),
    ("min_cool_f", "Min Cool Setpoint", 50, 80, 0.5, "°F", NumberMode.BOX),
    ("max_cool_f", "Max Cool Setpoint", 70, 92, 0.5, "°F", NumberMode.BOX),
    ("peak_max_temp_f", "Peak Max Indoor Temp", 70, 90, 0.5, "°F", NumberMode.BOX),
    ("precool_offset_f", "Precool Offset", 0, 8, 0.5, "°F", NumberMode.BOX),
]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_climate_persistence.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/ha_power_control/binary_sensor.py custom_components/ha_power_control/number.py tests/test_climate_persistence.py
git commit -m "feat: owns_climate reflects store flags; add precool_offset_f number"
```

---

## Task 15: End-to-end coordinator-driven cycle test

**Why:** Confidence that all the pieces (export tracker → policy → runner → store → owns_climate) compose correctly across simulated time.

**Files:**
- Test: `tests/test_climate_e2e.py`

- [ ] **Step 1: Write the test**

Create `tests/test_climate_e2e.py`:

```python
"""End-to-end: simulated tick sequence through coordinator + runner."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_power_control.const import (
    CONF_CLIMATE, CONF_INDOOR_TEMPS, CONF_NET_EXPORT_KWH,
    CONF_NET_IMPORT_KWH, CONF_NET_W, CONF_NET_W_SIGN, DOMAIN,
)


def _seed(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sensor.eagle_200_meter_power_demand", "-1.5",
        {"unit_of_measurement": "kW", "device_class": "power"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_delivered", "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "sensor.eagle_200_total_meter_energy_received", "0",
        {"unit_of_measurement": "kWh"},
    )
    hass.states.async_set(
        "climate.thermostat", "heat_cool",
        {"target_temp_high": 76.0, "target_temp_low": 68.0,
         "current_temperature": 78.0, "preset_mode": "home"},
    )
    hass.states.async_set(
        "sensor.bedroom_temperature", "78.0",
        {"unit_of_measurement": "°F"},
    )


def _entry_data() -> dict:
    return {
        CONF_NET_W: "sensor.eagle_200_meter_power_demand",
        CONF_NET_IMPORT_KWH: "sensor.eagle_200_total_meter_energy_delivered",
        CONF_NET_EXPORT_KWH: "sensor.eagle_200_total_meter_energy_received",
        CONF_CLIMATE: "climate.thermostat",
        CONF_INDOOR_TEMPS: ["sensor.bedroom_temperature"],
        CONF_NET_W_SIGN: 1,
    }


async def test_full_cycle_precool_then_peak_hold_then_restore(
    hass: HomeAssistant,
) -> None:
    _seed(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, data=_entry_data(),
        options={"dry_run": False, "climate_override_enabled": True},
    )
    entry.add_to_hass(hass)

    calls: list[dict] = []

    async def fake_service(call):
        calls.append(dict(call.data))
        # Reflect the write back into state so subsequent ticks see new target_high.
        cur = hass.states.get("climate.thermostat")
        attrs = dict(cur.attributes) if cur else {}
        attrs["target_temp_high"] = call.data["target_temp_high"]
        attrs["target_temp_low"] = call.data.get("target_temp_low", attrs.get("target_temp_low", 68.0))
        hass.states.async_set("climate.thermostat", "heat_cool", attrs)

    hass.services.async_register("climate", "set_temperature", fake_service)

    # Pre-peak weekday afternoon
    hass.config.time_zone = "America/Los_Angeles"
    base = datetime(2026, 5, 6, 16, 30, 0)  # 4:30pm M, 30 min before peak

    with patch(
        "custom_components.ha_power_control.coordinator.dt_util.utcnow",
        return_value=base,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # First tick — sustained-export needs ≥10 min; this is t=0 so no precool yet.
    coord = hass.data[DOMAIN][entry.entry_id]
    assert calls == []  # no setpoint write on first tick

    # Advance simulated time +700s (>10 min) and tick again
    with patch(
        "custom_components.ha_power_control.coordinator.dt_util.utcnow",
        return_value=base + timedelta(seconds=700),
    ):
        await coord.async_request_refresh()
        await hass.async_block_till_done()
    # Precool should have fired
    assert any(c.get("target_temp_high") == 72.0 for c in calls), (
        f"expected precool write to 72.0, got {calls}"
    )

    # Advance to peak window (5pm); peak-hold should fire
    with patch(
        "custom_components.ha_power_control.coordinator.dt_util.utcnow",
        return_value=datetime(2026, 5, 6, 17, 0, 30),
    ):
        await coord.async_request_refresh()
        await hass.async_block_till_done()
    assert any(c.get("target_temp_high") == 80.0 for c in calls)

    # Advance past peak end (8pm); restore originals
    with patch(
        "custom_components.ha_power_control.coordinator.dt_util.utcnow",
        return_value=datetime(2026, 5, 6, 20, 0, 30),
    ):
        await coord.async_request_refresh()
        await hass.async_block_till_done()
    # Final write must restore 76.0
    assert calls[-1].get("target_temp_high") == 76.0
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_climate_e2e.py -v`
Expected: PASS. If it fails on timezone handling, the patching of `dt_util.DEFAULT_TIME_ZONE` may need an alternative — replace the inner `with patch(...)` for `DEFAULT_TIME_ZONE` with `monkeypatch.setattr(...)` or set `hass.config.time_zone = "America/Los_Angeles"` before setup.

- [ ] **Step 3: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_climate_e2e.py
git commit -m "test: end-to-end precool→peak-hold→restore cycle"
```

---

## Task 16: Update README + bump manifest + tag v0.2.0

**Why:** v0.2.0 release. README must explain Mode B behavior, the dry-run default, and how to enable.

**Files:**
- Modify: `README.md`
- Modify: `custom_components/ha_power_control/manifest.json`
- Modify: `docs/HANDOFF.md` (replace P2 plan-of-attack with P3 plan-of-attack)

- [ ] **Step 1: Bump manifest version**

Edit `custom_components/ha_power_control/manifest.json` — change `"version": "0.1.0"` to `"version": "0.2.0"`.

- [ ] **Step 2: Append a P2 section to README.md**

Add a new `## P2 — Climate Controller (v0.2.0)` section. Suggested content:

```markdown
## P2 — Climate Controller (v0.2.0)

When excess solar is available, HA Power Control precools the house before the 5–8pm peak window and holds the thermostat at a configurable ceiling during peak hours.

**Behavior:**
- **Precool (before peak)**: when net export ≥ 200 W has been sustained for ≥10 minutes and peak begins within 60 minutes, the integration lowers `target_temp_high` by `precool_offset_f` (default 4 °F).
- **Peak hold (5–8pm M-F)**: at peak start, raises `target_temp_high` to `peak_max_temp_f` (default 80 °F) so the AC will not run unless the house climbs past the ceiling.
- **Restore (8pm)**: the original setpoint captured before precool is restored, clamped to `[min_cool_f, max_cool_f]` per the §7.1 invariant.

**Not yet implemented (deferred from P2 scope):**
- Mode A preset maintenance — the integration does not yet enforce a preset target outside the precool/peak-hold windows. Manual preset changes during off-peak hours are user-driven and will not be reverted.

**Safety:**
- Default is `dry_run=on` and `climate_override_enabled=off`. Both must be flipped explicitly to enable writes.
- Setpoint writes are clamped to `[min_cool_f, max_cool_f]` defensively.
- The integration only writes `target_temp_high`. It NEVER touches `target_temp_low`, so the heat threshold is preserved and the furnace will never be activated by the controller.
- If the user changes the thermostat manually, drift detection triggers a 30-minute cooldown; the integration will not fight the user.
- If the indoor temperature exceeds `peak_max_temp_f` during peak hold, the controller aborts hold and restores originals so the AC can run.
- All cycle state persists across HA restarts; the integration restores originals automatically on startup if a cycle was interrupted.

**Enable on live HA:**
1. Toggle `switch.dry_run` → off.
2. Toggle `switch.climate_override_enabled` → on.
3. Watch `binary_sensor.owns_climate` — flips on when the controller takes ownership.
```

Update the roadmap section: mark P2 ✅, set P3 (battery state machine — pending Delta 3 Max delivery) as next.

- [ ] **Step 3: Update HANDOFF.md**

Replace the "P2 — what's next" section with a "P3 — what's next" pointer to spec §6.1 (battery state machine), conditional on Delta 3 Max delivery.

- [ ] **Step 4: Run pre-merge gate**

```bash
ruff check custom_components tests
ruff format --check custom_components tests
pytest -q
python custom_components/ha_power_control/lovelace/validate.py
```

Expected: all green. If `ruff format --check` complains, run `ruff format custom_components tests` and re-stage.

- [ ] **Step 5: Commit + tag**

```bash
git add README.md docs/HANDOFF.md custom_components/ha_power_control/manifest.json
git commit -m "docs: P2 complete — climate controller (precool + peak-hold) v0.2.0"
git tag v0.2.0
```

- [ ] **Step 6: Update P2 plan execution-status header**

Add an execution-status header at the top of this file (`docs/superpowers/plans/2026-05-06-ha-power-control-p2.md`) listing all 16 tasks ✅ with their commit SHAs.

```bash
git add docs/superpowers/plans/2026-05-06-ha-power-control-p2.md
git commit -m "docs(plan): P2 execution complete — all 16 tasks ✅"
```

---

---

## Appendix A: Final assembled `decide()` reference

Tasks 4–10 build `decide()` incrementally with positional insertion instructions. The order of branches is load-bearing — cooldown must precede drift detection must precede restoration must precede peak-hold-steady must precede peak-hold-entry must precede precool-gates. After Task 10, the implementer should compare their assembled `policy/climate.py` to this reference. Branch labels match the `log_reason` strings.

```python
def decide(inp: ClimateInputs) -> Action:
    persisted = dict(inp.persisted)

    # 1. Master enable gate
    if not inp.options.get("climate_override_enabled", False):
        return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="override_disabled")

    # 2. Climate health gate
    if not _is_healthy(inp):
        return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="climate_unhealthy")

    # 3. Cooldown elapsed → clear; cooldown active → suppress
    cooldown_until = _parse_iso(persisted.get("cooldown_until"))
    if cooldown_until and inp.ts < cooldown_until:
        return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="in_cooldown")
    if cooldown_until and inp.ts >= cooldown_until:
        persisted["cooldown_until"] = None

    # 4. External-override drift detection
    #    Only meaningful when we have an active cycle or a recent write.
    if (
        persisted.get("precool_active")
        or persisted.get("peak_hold_active")
        or persisted.get("last_write_record") is not None
    ) and _drift_detected(inp):
        cd_min = inp.options["cooldown_min"]
        persisted["cooldown_until"] = (inp.ts + timedelta(minutes=cd_min)).isoformat()
        return Action(kind=ActionKind.SET_COOLDOWN, next_persisted=persisted, log_reason="drift_detected")

    captured = persisted.get("captured_originals")

    # 5. Peak window ended → restore
    if persisted.get("peak_hold_active") and not inp.in_peak_window and captured:
        persisted["peak_hold_active"] = False
        persisted["precool_active"] = False
        persisted["precool_ran_this_cycle"] = False
        persisted["captured_originals"] = None
        return Action(
            kind=ActionKind.RESTORE,
            target_high_f=_clamp(captured["target_high_f"], inp.options["min_cool_f"], inp.options["max_cool_f"]),
            preset=captured["preset"],
            next_persisted=persisted,
            log_reason="peak_window_ended",
        )

    # 6. Precool aborted (export collapsed or sleep window)
    if persisted.get("precool_active") and not inp.in_peak_window and captured:
        export_ok = (
            inp.export_run_seconds >= 600
            and inp.export_w >= inp.options["charge_threshold_w"]
        )
        sleeping = _in_sleep_window(inp.ts, inp.options["sleep_start_h"], inp.options["sleep_end_h"])
        if (not export_ok) or sleeping:
            persisted["precool_active"] = False
            persisted["precool_ran_this_cycle"] = False
            persisted["captured_originals"] = None
            return Action(
                kind=ActionKind.RESTORE,
                target_high_f=_clamp(captured["target_high_f"], inp.options["min_cool_f"], inp.options["max_cool_f"]),
                preset=captured["preset"],
                next_persisted=persisted,
                log_reason="precool_aborted",
            )

    # 7. Peak hold steady (with hard-exit on temp ceiling)
    if inp.in_peak_window and persisted.get("peak_hold_active"):
        if (
            inp.mean_indoor_f is not None
            and inp.mean_indoor_f > inp.options["peak_max_temp_f"]
            and captured is not None
        ):
            persisted["peak_hold_active"] = False
            persisted["precool_active"] = False
            persisted["precool_ran_this_cycle"] = False
            persisted["captured_originals"] = None
            return Action(
                kind=ActionKind.RESTORE,
                target_high_f=_clamp(captured["target_high_f"], inp.options["min_cool_f"], inp.options["max_cool_f"]),
                preset=captured["preset"],
                next_persisted=persisted,
                log_reason="hard_exit_temp_above_ceiling",
            )
        return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="peak_hold_steady")

    # 8. Peak-hold entry from active precool
    if inp.in_peak_window and persisted.get("precool_active"):
        if not persisted.get("precool_ran_this_cycle"):
            persisted["precool_active"] = False
            persisted["peak_hold_active"] = False
            return Action(
                kind=ActionKind.RESTORE,
                target_high_f=_clamp(captured["target_high_f"], inp.options["min_cool_f"], inp.options["max_cool_f"]),
                preset=captured["preset"],
                next_persisted=persisted,
                log_reason="abandon_partial_cycle",
            )
        persisted["precool_active"] = False
        persisted["peak_hold_active"] = True
        return Action(
            kind=ActionKind.PEAK_HOLD_START,
            target_high_f=_clamp(inp.options["peak_max_temp_f"], inp.options["min_cool_f"], inp.options["max_cool_f"]),
            next_persisted=persisted,
            log_reason="peak_hold_entry",
        )

    # 9. Cold-start mid-peak with stale captured_originals → abandon, restore
    if (
        inp.in_peak_window
        and captured
        and not persisted.get("precool_ran_this_cycle")
    ):
        persisted["peak_hold_active"] = False
        persisted["precool_active"] = False
        persisted["captured_originals"] = None
        return Action(
            kind=ActionKind.RESTORE,
            target_high_f=_clamp(captured["target_high_f"], inp.options["min_cool_f"], inp.options["max_cool_f"]),
            preset=captured["preset"],
            next_persisted=persisted,
            log_reason="cold_start_abandon",
        )

    # 10. Precool entry — all gates must pass
    if _precool_gates_pass(inp):
        captured_now = {
            "target_high_f": inp.climate_target_high_f,
            "target_low_f": inp.climate_target_low_f,
            "preset": inp.climate_preset,
            "captured_at": inp.ts.isoformat(),
        }
        new_high = _clamp(
            inp.climate_target_high_f - inp.options["precool_offset_f"],
            inp.options["min_cool_f"],
            inp.options["max_cool_f"],
        )
        persisted["captured_originals"] = captured_now
        persisted["precool_active"] = True
        persisted["precool_ran_this_cycle"] = True
        return Action(
            kind=ActionKind.PRECOOL_START,
            target_high_f=new_high,
            next_persisted=persisted,
            log_reason="precool_gates_passed",
        )

    # 11. Default
    return Action(kind=ActionKind.NOOP, next_persisted=persisted, log_reason="idle")
```

**Verification step at the end of Task 10:** diff your assembled `decide()` against this reference. The branches must appear in this order. If any branch is missing or out of order, individual unit tests may still pass but the full integration test (Task 15) will fail mysteriously.

---

## Self-Review Checklist

- [x] Spec §6.2 climate-controller behavior (precool, peak-hold, restore, hard exits, drift, persistence) — covered by Tasks 4–10, 13.
- [x] Spec §7.1 invariant (setpoint clamping) — Task 10.
- [x] Restart-recovery test required by §6.2 — Tasks 13, 15.
- [x] Dry-run gate enforced in single chokepoint — Task 11 (runner).
- [x] Switches persist to `entry.options` — Task 1.
- [x] `target_temp_low` never written; `target_temp_high` only — Task 11 (runner explicitly preserves low).
- [x] No `# TODO`, no "implement appropriate handling" placeholders — every step has full code.
- [x] Type consistency: `Action`, `ActionKind`, `ClimateInputs`, `ClimatePersisted` (dict shape) used identically across Tasks 4–14.
- [x] Mode A preset maintenance explicitly out of scope — preserved as future work.

## Risks / Edge Cases the Implementer Should Watch

1. **Tick cadence in tests**: the coordinator's update interval is 30 s. Tests must trigger ticks via `await coord.async_request_refresh()` after patching `dt_util.utcnow`, NOT via real time.
2. **Timezone**: `is_peak()` uses local time; the e2e test patches `DEFAULT_TIME_ZONE` to LA. If the patch doesn't stick, set `hass.config.time_zone = "America/Los_Angeles"` before `async_setup`.
3. **First-tick race on startup-restore**: `_maybe_restore_at_startup` runs before `async_config_entry_first_refresh`. The runner inside it must not read coordinator state; it pulls captured originals from the store directly.
4. **Holiday on a weekday**: `seconds_until_peak_start` already skips holidays. No special-case needed in the policy.
5. **Climate entity `unavailable`**: `_is_healthy` returns False → policy NOOPs. Persisted `precool_active` flag may stay true; that's correct — when entity recovers, the next tick will hit the abort path (export collapsed during outage) or peak-end and restore.
