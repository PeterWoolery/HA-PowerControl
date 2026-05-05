# HA Power Control — Design Spec

**Status:** Draft (pre-implementation)
**Date:** 2026-05-03
**Owner:** Peter (peter@research.bike)
**Repo (planned):** `ha-power-control` (HACS-installable Home Assistant custom integration, MIT license, open source)
**Target HA:** 2026.4.x (current installation: 2026.4.4 on 192.168.1.103, Proxmox VM)

---

## 1. Purpose

Build a Home Assistant custom integration that intelligently coordinates rooftop solar export, an EcoFlow Delta 3 Max battery (pass-through UPS, on order), and an Ecobee thermostat to **minimize the homeowner's PG&E true-up bill** under the **NEM 2.0 / E-TOU-D** tariff while preserving comfort, configurability, and Ecobee-native fallback behavior.

A custom Lovelace dashboard ships with the integration for administration. A long-term Influx + Grafana stack (out of integration scope) provides retrospective analysis. An ROI/sizing recommender advises on when adding panels or batteries is justified, given the explicit constraints of NEM 2.0 grandfathering.

---

## 2. Constraints from current setup (verified 2026-05-03 against live HA)

| Item | Value | Source |
|---|---|---|
| Tariff | E-TOU-D (Time-of-Use, Peak 5–8pm M-F, holidays excluded) | PG&E March 2026 bill (`MarchBill.pdf`) |
| NEM | NEM 2.0, grandfathered through ~2039 | Bill page 1 + user confirmation |
| CCA | San Jose Clean Energy (GreenSource) | Bill page 7 |
| Combined import rate, peak | ~$0.50/kWh ($0.38747 PG&E delivery + $0.11324 SJCE generation) | Bill pages 6–7 |
| Combined import rate, off-peak | ~$0.43/kWh ($0.34886 + $0.07921) | Bill pages 6–7 |
| Peak/off-peak delta | **$0.07/kWh** (small — limits arbitrage value) | Derived |
| Export credit | Offsets imports at same TOU rate within true-up year; net surplus paid at ~$0.03–0.05/kWh wholesale at annual true-up | NEM 2.0 rules |
| Base Services Charge | ~$24/mo fixed (unavoidable) | Bill page 5 |
| YTD net usage (9 mo) | 5,279 kWh net imported (1,058 peak + 4,222 off-peak) | Bill page 3 |
| YTD NEM balance | $1,612.54 → ~$2,150 projected at 06/2026 true-up | Bill page 3 |
| Ecobee | Single thermostat, `climate.thermostat`, with remote sensors Bedroom / Elliott / Matteson / Thermostat | HA states |
| Ecobee presets | `home`, `Home NoSolar`, `sleep`, `away`, `away_indefinitely` (user maintains "Home NoSolar" manually today) | HA states |
| Eagle 200 (whole-house net meter) | `sensor.eagle_200_meter_power_demand` (kW), `*_total_meter_energy_delivered` (imported kWh), `*_total_meter_energy_received` (exported kWh) — local API | HA states |
| Solar production sensor | **None directly available** — no SolarEdge integration yet, Emporia clamps on solar 220V exist but channels 5/7/8/10 read 0 (config issue, user to verify). `solar_w` is **optional throughout the design**; battery logic does not require it (uses Eagle `export_w` exclusively). Resolution is a P5 deliverable. | HA states |
| EcoFlow Delta 3 Max | **Not yet present** — device on order; integration shell installed | HA states |
| Indoor temp sensors (initial set) | `sensor.bedroom_temperature` 71.6°F, `sensor.elliott_temperature` 70.1°F, `sensor.matteson_temperature` 70.5°F, `sensor.thermostat_temperature` 69.4°F | HA states |
| Existing climate-touching automations | `automation.hvac_leak`, `automation.aqi_hvac`, `automation.aqi_hvac_fan_off` (none write setpoint) | HA states |

### 2.1 Adversarial economic premise (must be honored)

Under NEM 2.0 + E-TOU-D, the dollar value of cycling battery storage is **far smaller than naive peak/off-peak delta math suggests**, because every kWh stored forfeits the export credit that kWh would have earned at the *same* retail TOU rate.

**Honest derivation** for 1 kWh of surplus solar generated off-peak, used to offset 1 kWh of peak load:

- **Strategy A — export now, import at peak:**
  - Solar exports 1 kWh → bank $0.43 credit (off-peak retail).
  - At peak, import 1 kWh → cost $0.50.
  - **Net day cost: $0.07.**
- **Strategy B — store now, discharge at peak:**
  - Solar charges battery; ~0.87 kWh delivered at peak (15% RTE loss).
  - No export credit earned ($0.00).
  - Still import 0.13 kWh at peak → cost $0.065.
  - **Net day cost: $0.065.**
- **Storage advantage: ~$0.005/kWh.**

For 2 kWh/day cycled = **~$3.65/year**. The Delta 3 Max **cannot pay back its capex on NEM 2.0 arbitrage** — full stop. The same constraint applies to adding battery capacity. The recommender must report this honestly.

Real value of the project under NEM 2.0:

1. **Backup readiness** — protection against PG&E PSPS / outages (the dominant economic value).
2. **Operational knowledge** — measured indoor comfort, real load profiling, dashboarding.
3. **Climate optimization** — precool/peak-hold reduces *consumption* during peak rather than relying on storage; this is largely independent of battery economics.
4. **Future hedging** — if NEM 2.0 grandfathering is ever rescinded (legislative risk), per-kWh storage value rises sharply because export credits collapse to wholesale.
5. **True-up reduction via consumption shifting** — every kWh moved from peak to off-peak (e.g., delaying laundry, dishwasher, EV charging) saves $0.07/kWh whether or not a battery is involved.

The recommender must distinguish:
- **Storage capex ROI** (poor under NEM 2.0; primarily backup + hedge)
- **Panel capex ROI** (good under NEM 2.0 *up to* the 110% historical-usage cap; exceeding the cap risks NEM 2.0 transition and is asymmetrically destructive)
- **Behavioral / load-shift ROI** (often the best lever; no capex)

Adding panels under NEM 2.0 is constrained by the **110% historical-usage cap**; exceeding it can trigger NEM 3.0 transition and destroy the grandfathered economics.

---

## 3. Architecture

```
┌────────────────── Home Assistant (192.168.1.103) ────────────────────┐
│                                                                      │
│  Existing integrations          ┌─── ha_power_control (NEW) ───┐     │
│  (read-only consumers):         │                              │     │
│   • ecobee.*                    │  DataUpdateCoordinator (30s) │     │
│   • rainforest_eagle.*          │   → PowerState snapshot      │     │
│   • emporia_vue.*               │                              │     │
│   • ecoflow_cloud (HACS)        │  PolicyEngine                │     │
│   • Forecast.Solar              │   ├─ TOU calculator          │     │
│   • Indoor temp sensors         │   ├─ Battery state machine   │     │
│                                 │   ├─ Climate controller      │     │
│  Long-term storage              │   └─ True-up projector       │     │
│   • InfluxDB add-on (NEW)       │                              │     │
│   • Grafana add-on (NEW)        │  ROIRecommender (offline)    │     │
│                                 │                              │     │
│                                 │  Entities (sensor, switch,   │     │
│                                 │   number, select, button,    │     │
│                                 │   binary_sensor)             │     │
│                                 │                              │     │
│                                 │  Services + config flow      │     │
│                                 │  Lovelace dashboard YAML     │     │
│                                 └──────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

**Approach: Single monolithic custom integration** (Approach A from brainstorm). Selected for:
- Simplicity of HACS install for end users
- Single config flow, single repo
- Lower contributor barrier vs splitting into integration + library

Trade-off accepted: policy logic lives inside the integration (less pure unit-testable), mitigated by keeping `policy/` modules dependency-injected with no HA imports above their own boundary.

---

## 4. Components & files

```
ha-power-control/
├── README.md                       installation, screenshots, NEM 2.0 caveats, dashboard import
├── LICENSE                         MIT
├── hacs.json
├── pyproject.toml                  ruff + pytest config; pins python-holidays version
├── custom_components/
│   └── ha_power_control/
│       ├── __init__.py             setup_entry, unload_entry, services registration,
│       │                             async_forward_entry_setups for all platforms
│       ├── manifest.json
│       ├── const.py                DOMAIN, defaults, E-TOU-D constants, holiday list version pin
│       ├── config_flow.py          UI: select source entities, validate climate hvac_mode
│       ├── options_flow.py         tuneables (all defaults overridable here)
│       ├── coordinator.py          DataUpdateCoordinator (30s) → PowerState
│       ├── models.py               PowerState, PolicyDecision dataclasses
│       ├── tou.py                  E-TOU-D peak window + holiday calc (python-holidays)
│       ├── entity_map.py           resolved entity_ids + validation
│       ├── store.py                homeassistant.helpers.storage.Store wrapper
│       │                             (persists captured originals, precool flags, last-write hashes)
│       ├── policy/
│       │   ├── __init__.py         PolicyEngine entrypoint
│       │   ├── state_machine.py    IDLE / CHARGING_FROM_SOLAR / DISCHARGING / EMERGENCY_CHARGE
│       │   ├── peak_shave.py       discharge rules during 5-8pm window
│       │   ├── charge_control.py   closed-loop charge-rate modulation
│       │   ├── climate.py          Ecobee precool/peak-hold controller
│       │   └── trueup.py           rolling NEM 2.0 balance projector with versioned rate source
│       ├── recommender/
│       │   ├── __init__.py         ROI calculator (offline, callable via service)
│       │   └── sizing.py           panel/battery sizing under NEM 2.0 110% cap
│       ├── sensor.py               platform: mean indoor temp, projected true-up, today's savings
│       ├── binary_sensor.py        platform: in_peak_window, charging, discharging,
│       │                             owns_climate, climate_healthy
│       ├── switch.py               platform: per-temp-sensor inclusion, climate_override, dry_run
│       ├── number.py               platform: all numeric tuneables (see §4.1)
│       ├── select.py               platform: operating_mode, climate_preset_target
│       ├── button.py               platform: force_charge, force_discharge, run_recommender
│       ├── services.yaml
│       └── lovelace/
│           └── dashboard.yaml      reference Lovelace YAML
├── scripts/
│   └── live_smoke.py               read-only HA REST harness; runs PolicyEngine.decide
│                                     against live state, prints would-be actions
└── tests/
    ├── conftest.py
    ├── test_tou.py
    ├── test_policy_state_machine.py
    ├── test_peak_shave.py
    ├── test_charge_control.py
    ├── test_climate.py
    ├── test_climate_persistence.py persistence + restart recovery (S8, S15)
    ├── test_trueup.py
    ├── test_recommender.py
    ├── test_coordinator.py
    └── fixtures/
        └── march_bill_2026.json    regression fixture extracted from MarchBill.pdf
```

**Platform module location (HA convention).** HA discovers platforms via `async_forward_entry_setups(entry, ["sensor", "switch", ...])` in `__init__.py`, importing `custom_components.ha_power_control.sensor`, `.switch`, etc. Platform modules live at the integration root (not under a `platforms/` subdirectory), per the standard custom-integration layout. Putting them in a subdirectory is possible only with explicit re-exports and is non-idiomatic; we do not do this.

### 4.1 User-facing entities

| Entity | Type | Purpose |
|---|---|---|
| `sensor.power_control_mean_indoor_temp` | sensor (°F) | Mean of *included* sensors only; `unknown` if all included sensors invalid |
| `sensor.power_control_net_w` | sensor (W) | Eagle 200 net, signed (+ import, − export) |
| `sensor.power_control_export_w` | sensor (W) | `max(0, -net_w)` |
| `sensor.power_control_solar_w` | sensor (W) | From Emporia solar clamp if configured; else `unknown` |
| `sensor.power_control_battery_soc` | sensor (%) | EcoFlow SoC; `unavailable` until device present |
| `sensor.power_control_projected_trueup` | sensor (USD) | Projected balance at next 06/YYYY true-up |
| `sensor.power_control_today_peak_savings` | sensor (USD) | Estimated savings from today's peak-shave |
| `sensor.power_control_state` | sensor | Current state-machine state name |
| `binary_sensor.power_control_in_peak_window` | binary | True 5–8pm M-F (excluding holidays) |
| `binary_sensor.power_control_battery_charging` | binary |  |
| `binary_sensor.power_control_battery_discharging` | binary |  |
| `binary_sensor.power_control_owns_climate` | binary | True when integration is actively writing setpoints |
| `binary_sensor.power_control_climate_healthy` | binary | False if Ecobee unavailable |
| `switch.power_control_include_<sensor_slug>` | switch | One per indoor temp sensor; toggles inclusion in mean |
| `switch.power_control_climate_override_enabled` | switch | Master enable for climate writes |
| `switch.power_control_dry_run` | switch | Log decisions without executing |
| `number.power_control_battery_reserve_pct` | number | Min SoC retained for backup (default 20) |
| `number.power_control_max_charge_w` | number | Cap charge rate (default 1200, max 1500) |
| `number.power_control_precool_offset_f` | number | How much below current target to lower during precool (default 4) |
| `number.power_control_peak_max_temp_f` | number | Hard ceiling for peak-hold (default 80) |
| `number.power_control_min_cool_f` / `max_cool_f` | number | Safety bounds for any setpoint write (defaults 65, 82) |
| `number.power_control_charge_threshold_w` | number | Min export to start charging (default 200) |
| `number.power_control_min_charge_w` | number | Below this commanded rate, stop-timer starts (default 50) |
| `number.power_control_charge_buffer_w` | number | Headroom kept on export side during modulation (default 100) |
| `number.power_control_discharge_min_import_w` | number | Min measured import before discharging (default 100) — see S6 |
| `number.power_control_force_override_min` | number | Duration of force-charge/discharge override (default 60) |
| `number.power_control_cooldown_min` | number | Cooldown after detected external Ecobee change (default 30) |
| `number.power_control_drift_tolerance_f` | number | Per-unit tolerance for write-drift detection (default 0.5) |
| `number.power_control_drift_grace_s` | number | Grace window after our write before drift counts (default 60) |
| `number.power_control_sleep_start_h` / `sleep_end_h` | number | Sleep window where climate logic disengages (default 22, 6) |
| `number.power_control_trueup_month` | number | Month (1–12) of annual NEM true-up cycle (default 6 = June) |
| `select.power_control_mode` | select | `auto` / `peak_shave_only` / `charge_only` / `off` |
| `select.power_control_climate_preset_target` | select | Default preset to maintain when not actively precooling |
| `button.power_control_force_charge` | button | Manual override 60 min |
| `button.power_control_force_discharge` | button | Manual override 60 min |
| `button.power_control_run_recommender` | button | Recompute ROI/sizing |
| `button.power_control_snapshot_state` | button | Dump 30-min trace JSON |

### 4.2 Services

- `ha_power_control.set_battery_mode(mode, duration_minutes)`
- `ha_power_control.request_cool_cycle(target_f, max_minutes)`
- `ha_power_control.recompute_recommender`
- `ha_power_control.snapshot_state`

### 4.3 Dependencies (manifest.json)

The integration **does not bundle** integrations for Ecobee/Eagle/EcoFlow/Emporia and **does not declare them as `dependencies`** in the manifest. HA `dependencies` are hard requirements; declaring missing or misnamed domains there blocks setup. Instead:

- The manifest's `dependencies` field is empty (or contains only HA core helpers we actually need, e.g., `recorder`).
- Source integrations are discovered at config-flow time via entity selectors. The user picks whichever entity provides each role (climate, net-meter, etc.). If a required role is unfilled, that capability simply remains disabled — battery logic without a battery SoC entity, climate logic without a climate entity, etc.
- `after_dependencies` (a soft hint for load order) may list `recorder` to ensure historical statistics are available at startup, but is not used for source integrations.

Python deps in manifest `requirements`: pin `python-holidays>=0.50` (versioned holiday lookup; addresses S12).

---

## 5. Data flow

Every 30s the coordinator builds a `PowerState`:

```python
@dataclass(frozen=True)
class PowerState:
    ts: datetime
    net_w: float                          # signed: + import, - export
    export_w: float                       # = max(0, -net_w)
    solar_w: Optional[float]              # from Emporia if configured
    battery: Optional[BatteryState]       # None until device present
    climate: ClimateState
    indoor_temps: dict[str, float]        # included only, unknown filtered
    mean_indoor_f: Optional[float]
    tou_period: Literal["peak", "off_peak"]
    in_peak_window: bool
    today_kwh_imported: float
    today_kwh_exported: float
    today_peak_savings_usd: float
```

`PolicyEngine.decide(state, options) → PolicyDecision` is a pure function. The coordinator dispatches the resulting service calls.

---

## 6. Policy logic

### 6.1 Battery state machine

States: **IDLE**, **CHARGING_FROM_SOLAR**, **DISCHARGING**, **EMERGENCY_CHARGE**.

(`PRECHARGE_FROM_GRID` and a separate `HOLDING` state were considered and rejected — under NEM 2.0 the arbitrage value of grid-charging is negative once round-trip loss is counted, and `IDLE` already represents the "battery present but inactive" condition.)

**Charge-rate modulation**: when `CHARGING_FROM_SOLAR`, the commanded AC input rate is recomputed every tick as
`charge_w = clamp(export_w − charge_buffer_w, 0, max_charge_w)`
where `charge_buffer_w` (default 100W) ensures we don't pull the household into net-import. This is closed-loop: the rate self-throttles as house loads come on and self-grows as they drop. Eliminates the start/stop oscillation that a simple threshold-based scheme produces (charging full-rate would crash export to ~0 and immediately violate the start condition).

Transitions (battery present):

```
IDLE
  → CHARGING_FROM_SOLAR  if export_w ≥ charge_threshold_w (default 200W)
                         AND soc < soc_max_pct
                         AND ¬in_peak_window
                         AND mode ∈ {auto, charge_only}
  → DISCHARGING          if in_peak_window
                         AND soc > battery_reserve_pct
                         AND net_w ≥ discharge_min_import_w  (S6: don't discharge while exporting)
                         AND mode ∈ {auto, peak_shave_only}
  → EMERGENCY_CHARGE     if soc < battery_reserve_pct
                         AND mode ≠ off
                         (S9 resolution: mode=off means absolute no-command;
                          backup-reserve floor enforced by setting reserve to 0
                          if user genuinely wants no charging behavior at all)

CHARGING_FROM_SOLAR
  → IDLE                 if commanded charge_w < min_charge_w
                            sustained for ≥5 min (timer via async_track_point_in_time,
                            NOT tick-counted — addresses S11)
  → IDLE                 if soc ≥ soc_max_pct
  → IDLE                 if mode change away from {auto, charge_only}
  → DISCHARGING          when in_peak_window starts AND discharge guards (S6) pass

DISCHARGING
  → IDLE                 if soc ≤ battery_reserve_pct
  → IDLE                 if in_peak_window ends
  → IDLE                 if net_w < discharge_min_import_w sustained ≥1 min
                         (we're already exporting; further discharge wastes RTE)
  → IDLE                 if mode change away from {auto, peak_shave_only}

EMERGENCY_CHARGE
  → IDLE                 if soc ≥ battery_reserve_pct
                         (uses minimal grid charge rate, default 300W,
                          to avoid worsening peak imports if it occurs in peak)
```

**`mode = off` semantics (resolves S9):** absolute no-command mode. The integration reads but never commands the battery, even for reserve charging. If the user wants the battery off-grid for backup only, `mode = off` is the correct setting.

**Manual override buttons** (resolves S14):
- `force_charge_now`: pushes state machine into `CHARGING_FROM_SOLAR` for `force_override_min` (default 60). **Respects export-only charging**: if `export_w < min_charge_w`, the override sits at zero command rate (logged as "force_charge active but no export"). Force does **not** enable grid charging. A separate `force_grid_charge_now` button is intentionally **not** provided in v1 because grid-charging is uneconomic under NEM 2.0 and adds a footgun.
- `force_discharge_now`: pushes state machine into `DISCHARGING` for `force_override_min`. Bypasses the `in_peak_window` requirement but **not** the SoC reserve floor or the `discharge_min_import_w` guard.
- Re-press while active **extends** the override by another `force_override_min`.
- `mode = off` immediately cancels any active force-override and returns to IDLE.
- A force-override that conflicts with hard invariants (e.g., force_discharge below reserve) is rejected with a logged reason and a persistent notification.

**Hysteresis on charge stop**: the 5-min low-export timer is started only when *measured* export drops below `min_charge_w` *while* commanded charge_w is at or below available export — this distinguishes "sun went away" from "house load spiked momentarily." The timer uses `async_track_point_in_time(scheduled_at)` (wall-clock), not 30s-tick counts, to be robust to event-loop stalls (S11).

### 6.2 Climate controller

Ecobee is **assumed to be in `heat_cool` (auto) mode** with `target_temp_high` / `target_temp_low` attributes available in user's configured unit system (°F or °C; integration normalizes to °F internally and converts on write).

**Config-flow validation (addresses S4):**
- At config-flow submission, integration reads `climate.<entity>` state and verifies:
  - `state.state == "heat_cool"` AND `target_temp_high` and `target_temp_low` are both numeric, OR
  - integration warns the user that climate logic will be **disabled until** the thermostat is in `heat_cool` mode.
- At runtime, every tick re-checks the climate `state` value. If it has drifted to `heat`, `cool`, `off`, etc., the climate controller no-ops for that tick and emits `binary_sensor.power_control_climate_healthy = off`. Restoration is automatic when mode returns to `heat_cool`.
- Unit normalization: integration reads `hass.config.units.temperature_unit` to decide write format and reads `attributes.unit_of_measurement` for the climate entity for sanity. Mismatches log a warning and disable climate writes.

Per HA `climate` semantics in `heat_cool` mode:
- `target_temp_high` = **cooling threshold** (AC runs when room temp exceeds this)
- `target_temp_low` = **heating threshold** (heat runs when room temp falls below this)

The controller **only manipulates `target_temp_high`** for cooling actions. `target_temp_low` is left untouched to avoid accidentally activating the furnace.

Climate is controlled in two modes that compose:

**Mode A — Preset maintenance (default, low touch):**
Outside precool/peak-hold windows, integration ensures `climate.thermostat` is set to `select.power_control_climate_preset_target` (default `home`). User's existing `Home NoSolar` preset remains usable manually.

**Mode B — Precool + peak-hold (active intervention, single contiguous action):**

The action has **two phases that flow into each other without a gap**:

*Phase 1 — Precool*: fires when **all** are true:
- `export_w ≥ charge_threshold_w` for ≥10 min (proxy for "excess solar present")
- `0 < time_to_peak ≤ precool_lead_min` (default 60 min)
- `mean_indoor_f > peak_max_temp_f − precool_offset_f`
- Not in user-defined sleep window
- `climate_override_enabled = on` and `dry_run = off`

Action: capture originals `(target_high, target_low, preset)`. Write `target_high := captured.target_high − precool_offset_f` (default 4°F lower → drives AC to run, pre-cools house). Phase 1 holds **until peak start**, not for a fixed duration — this closes the precool/peak-hold gap.

*Phase 2 — Peak-hold*: at `in_peak_window` rising edge, **without restoring originals**, write `target_high := peak_max_temp_f` (default 80°F → suppresses AC unless temp climbs past ceiling).

*Restore*: at `in_peak_window` falling edge (8:00:01pm), restore captured originals exactly.

If precool conditions cease before peak (e.g., export collapses, sleep window starts), restore captured originals immediately and do not enter Phase 2.

**Hard exits during peak-hold:**
- If `mean_indoor_f > peak_max_temp_f` → abort hold, restore originals, allow AC.
- If user touches Ecobee (setpoint or preset changes from outside our writes) → **stop writing**, do **not** overwrite the user's choice, disable override for `cooldown_min` (default 30 min). (S7 fix: never fight the user; only restore originals at scheduled action end, or at restart-recovery, or if the user-set state itself violates safety bounds — `target_temp_high` outside `[min_cool_f, max_cool_f]`.)
- If `climate.thermostat` becomes unavailable → no-op until healthy; restore-on-recovery uses persisted captured originals from `Store`.

**Detection of external Ecobee changes (S7 fix):**
- Each write commits a record `{written_at: ts, target_high_value, preset_value}` to the integration's `Store`.
- Each tick compares current state to the most recent committed record:
  - If `(now − written_at) < drift_grace_s` (default 60), assume the write is in flight; do not flag drift.
  - Once outside grace, drift is `|current.target_high − written.target_high| > drift_tolerance_f` (default 0.5°F) **or** `current.preset != written.preset`.
  - Drift detected → enter cooldown (S7); do not auto-revert.

**Persistence (resolves S8 + S15):**
- `homeassistant.helpers.storage.Store` (key `ha_power_control.climate_state`, version 1) holds:
  - `captured_originals: {target_high_f, target_low_f, preset, captured_at}`
  - `precool_active: bool`
  - `peak_hold_active: bool`
  - `precool_ran_this_cycle: bool` — set true when Phase 1 runs; required-true for Phase 2 to execute (otherwise Phase 2 no-ops and logs).
  - `last_write_record: {target_high, preset, written_at}`
- Save on every state-changing transition (precool start, peak-hold start, restore, override detect).
- Restore-on-startup: if `precool_active` or `peak_hold_active` is true and `captured_originals` is set, immediately write originals on coordinator first-tick and clear flags. If `peak_hold_active` is true but `precool_ran_this_cycle` is false (data corruption / cold start mid-cycle), abandon the cycle and restore originals — do not enter Phase 2 from a partial state.
- Restart-recovery test (`test_climate_persistence.py`) explicitly simulates HA restart at every active-cycle moment.

### 6.3 Mean indoor temperature

```
included_temps = {
    eid: state.indoor_temps[eid]
    for eid in user_included_sensors
    if state.indoor_temps.get(eid) is not None
}
mean_indoor_f = sum(included_temps.values()) / len(included_temps)
                  if included_temps else None
```

User toggles inclusion per sensor via `switch.power_control_include_*`. Computed mean is informational and feeds the climate controller only.

### 6.4 ROI / sizing recommender

**True-up cycle (S10 fix):** the recommender and the `sensor.power_control_projected_trueup` projector both consume `number.power_control_trueup_month` (default 6 = June, configurable). User reads their bill's true-up month from the "True-Up statement (MM/YYYY)" line on PG&E NEM bills and sets accordingly.

**Rate-source versioning (S10 fix):** rates and tariff structure are loaded from a YAML rate-table fixture under `custom_components/ha_power_control/rates/etoud_<effective_date>.yaml` keyed by effective date. The integration ships with `etoud_2026-03-01.yaml` (post-Base-Services-Charge restructure) reflecting `MarchBill.pdf` exactly. Rates are loaded by closest-not-after-today date. Tests pin the fixture explicitly. Adding new rate periods is a YAML change, not a code change.

**Projector inputs (computed vs supplied):**
- *Computed by integration*: peak kWh, off-peak kWh, generation credit (TOU-rate × export kWh), Net Usage charges, NBC × kWh, NBC Net Usage Adjustment, monthly cumulative balance carry-forward.
- *Supplied by user / config*: rate-table version, true-up month, PCIA rate (varies annually by NEM vintage; `MarchBill.pdf` shows "2018 Vintaged PCIA"), Franchise Fee Surcharge rate, San Jose Utility Users' Tax (5.0%), San Jose Franchise Surcharge rate, SJCE generation rates (peak / off-peak), Energy Commission Surcharge.
- *Out of scope*: Climate Credit (annual one-time, hand-applied on bill), gas charges.

Inputs to recommender service: 12 months of HA Energy data (or bill data via fixture), current rate plan, NEM vintage, current array size, current battery capacity, candidate addition (panel kWh/yr or battery kWh).

Outputs:
- Annual $ saved by candidate addition (under NEM 2.0 110% cap modeling)
- Payback period (years)
- Boolean: would addition risk crossing 110% cap and triggering NEM 3.0 transition

Honest reporting (per §2.1):
- Additional panels save at full retail TOU rates **only up to** historical 110%; beyond that, the user risks NEM 2.0 transition and the recommender flags this as **asymmetric tail risk** rather than a marginal cost.
- Battery storage *cycle* value under NEM 2.0 is bounded by RTE-loss-driven economics (~$0.005/kWh of throughput). Cycle arbitrage is reported as a small dollar number, **explicitly labeled** "primarily backup, not arbitrage."
- Behavioral load-shifting (moving kWh from peak to off-peak) saves the full $0.07/kWh delta and is reported as the highest-leverage non-capex action.

The recommender refuses to project ROI improvements that contradict these bounds, even when user-supplied parameters would otherwise produce a positive number.

**Output structure (every recommender run emits all rows):**

| Value lever | Annual $ | Confidence | Notes |
|---|---|---|---|
| Cycle arbitrage (battery) | small | high | RTE-bounded under NEM 2.0; "primarily backup, not arbitrage" |
| Backup readiness (battery) | $X estimated | medium | User-supplied probability + duration of PSPS / outage events; default 1 × 8h/yr |
| NEM-vintage hedge (battery) | $Y estimated | low | Conditional on grandfathering ever ending; user supplies subjective probability; default 0 |
| Comfort / climate optimization | $Z | high | Precool + peak-hold avoided AC kWh × peak rate, measured from operation |
| Behavioral load-shift | $W | high | kWh moved peak→off-peak × $0.07; measured from HA Energy data |
| Additional panels (≤110% cap) | $V | high | Retail-TOU savings on incremental kWh, capped at 110% of historical use |
| **Asymmetric risk: panels >110% cap** | flagged | n/a | Triggers NEM 3.0 transition warning; not a $ figure |

The recommender's verdict line is the **sum of high-confidence rows** plus a separate "additional value if assumptions hold" line for medium/low confidence. Battery payback is computed as `capex / (sum of all rows attributable to battery)`, not as `capex / cycle_arbitrage` alone, so the report represents the full case for owning storage rather than a cycle-arbitrage-only verdict.

---

## 7. Error handling & invariants

### 7.1 Hard invariants (asserted in policy code)

- `0 ≤ battery_reserve_pct ≤ soc_max_pct ≤ 100`
- `0 ≤ max_charge_w ≤ 1500`
- `0 ≤ precool_offset_f ≤ 8`
- All setpoint writes ∈ `[min_cool_f, max_cool_f]` ∩ `[ecobee.min_temp, ecobee.max_temp]`
- Never simultaneously CHARGE and DISCHARGE
- Never write setpoint if `climate_override_enabled = off` or `dry_run = on`

### 7.2 Failure modes

| Failure | Detection | Response |
|---|---|---|
| Eagle sensor stale >5 min | `last_changed` | Mark `net_w` unknown; pause battery commands; climate falls back to Mode A |
| Climate `state` not `heat_cool` | tick check on `state.state` | Climate controller no-ops; `climate_healthy = off`; auto-restore when mode returns |
| Climate unit mismatch | `unit_of_measurement` ≠ `hass.config.units.temperature_unit` | Disable climate writes; log warning |
| Ecobee unavailable | state = `unavailable` | Skip climate tick; `climate_healthy = off` |
| EcoFlow lag >2 min | `last_updated` on SoC | Hold last mode; no new charge/discharge commands |
| All included indoor temps unknown | filtered set empty | `mean_indoor_f = unknown`; precool disabled |
| **Partial indoor-temp failure (≥1 stale, ≥1 valid)** (S16) | dict-filter retains ≥1 sensor | Compute mean over valid set; emit info log; raise warning notification only if >50% of included sensors stale for >10 min |
| Setpoint write rejected | service exception | Log, retry once at +30s, then disable override + raise persistent notification |
| External setpoint change (Ecobee app/touch) | written ≠ current beyond grace+tolerance | Stop writing; do **not** revert user's value (S7); enter override cooldown |
| Integration crash mid-precool / mid-peak-hold | startup checks `Store` flags | Restore captured originals from `Store`; abandon cycle; clear flags (S8, S15) |
| User flips `mode = off` | select changed | Cancel pending; restore last-known preset; battery commands cease completely (S9) |
| HA restart | normal HACS lifecycle | `Store` survives; entities restore; coordinator re-runs first tick within 30s |

### 7.3 Safety rails

- **Original-target capture**: every climate intervention persists captured originals to entity state before writing; restore on revert *and* on restart recovery.
- **Override cooldown**: 30 min minimum after detected manual override.
- **Hard ceiling**: integration never raises cool target above `peak_max_temp_f`.
- **Sleep window**: precool/peak-hold inactive 22:00–06:00 by default.
- **Dry-run mode**: ships ON for first install. User must opt in to live writes.
- **Battery reserve floor**: hard. Discharge stops at reserve even mid-peak.
- **Conflict-aware**: integration emits `binary_sensor.power_control_owns_climate`; other automations should check this and back off.

---

## 8. Configuration flow

1. **Welcome** — explanation, NEM 2.0 caveats with link to bill assumptions.
2. **Source entities** — entity selectors:
   - Net-meter power (W or kW, signed)
   - Net-meter import accumulator (kWh)
   - Net-meter export accumulator (kWh)
   - Solar AC sensor (optional, defaults to derived export)
   - Climate entity (Ecobee `climate.*`)
   - Indoor temp sensors (multi-select)
   - Battery SoC sensor (optional; integration runs in monitor-only without)
   - Battery AC-input/output sensors (optional)
   - Battery charge-enable switch entity (optional)
3. **Sign convention** — defaults to the documented `rainforest_eagle` semantics (positive = importing). User can flip the sign in advanced options if their integration version reverses it. No "calibration test" required at install.
4. **Tariff** — preselected E-TOU-D, peak 5–8pm M-F, holidays NERC list. User confirms or edits rates.
5. **Confirm** — show summary, write entry.

Options flow (post-install) exposes all `number`/`select` defaults for tuning.

---

## 9. Testing strategy

### 9.1 Unit (pure-Python)

- `test_tou.py`: peak boundaries (4:59/5:00/8:00/8:01), weekends, NERC holidays.
- `test_policy_state_machine.py`: every transition; idempotency.
- `test_peak_shave.py`, `test_charge_control.py`: discharge respects reserve; charge respects `charge_threshold_w` and 5-min hysteresis.
- `test_climate.py`: precool fires only when all conditions met; revert exact; manual-override cooldown; never out-of-bounds; `dry_run` blocks writes.
- `test_trueup.py`: cumulative NEM 2.0 monthly balance reproduces `MarchBill.pdf` figures within $1, with each line item asserted independently:
  - Net Usage Peak kWh × peak rate
  - Net Usage Off-Peak kWh × off-peak rate
  - NBC Net Usage Adjustment
  - State-Mandated Non-Bypassable Charge
  - Generation Credit (SJCE → PG&E)
  - Power Charge Indifference Adjustment (PCIA)
  - Franchise Fee Surcharge
  - San Jose Utility Users' Tax (5.0%)
  - San Jose Franchise Surcharge
  - SJCE Generation On-Peak / Off-Peak charges
  - Local Utility Users Tax (SJCE side)
  - Energy Commission Surcharge
  - Cumulative balance carry-forward across months
- `test_recommender.py`: refuses to over-project under 110% NEM 2.0 cap.

### 9.2 Integration (`pytest-homeassistant-custom-component`)

- Config flow happy + missing-EcoFlow paths.
- Coordinator tick with mocked entities.
- Entity registration completeness.
- Service calls end-to-end.

### 9.3 Live shadow harness

- `scripts/live_smoke.py` polls real HA REST, runs policy, prints would-be actions without commanding.
- `dry_run = true` ships as default for first install. User must explicitly enable live writes after observing 1–2 weeks of dry-run logs.

### 9.4 Pre-merge gate

- `ruff check` (zero warnings)
- `ruff format --check`
- `pytest -q --cov=custom_components.ha_power_control --cov-fail-under=85`
- `python -m custom_components.ha_power_control.lovelace.validate dashboard.yaml` — a small in-repo validator that loads `dashboard.yaml` with `yaml.safe_load`, runs it through `homeassistant.util.yaml.parse_yaml` schema checks, and verifies all referenced entity_ids match patterns the integration will register. (S17 — `homeassistant-cli check-config` requires a full HA config dir and is unsuitable for a standalone Lovelace YAML; this in-repo validator is the actual gate.)

---

## 10. Phasing

| Phase | Scope | Deliverable |
|---|---|---|
| **P1 — Acquisition + monitoring** | PowerState coordinator, mean-temp sensor with inclusion switches, projected true-up, dashboard with read-only panels | First HACS release `0.1.0`; battery-absent and ROI mode functional |
| **P2 — Climate controller** | Precool + peak-hold; override cooldown; dry-run default | `0.2.0`; live writes after user opts in |
| **P3 — Battery controller** | After Delta 3 Max arrives + EcoFlow Cloud entities populated; charge-from-solar + peak-shave discharge | `0.3.0` |
| **P4 — ROI / sizing recommender** | Offline calculator, panel and battery candidates, NEM 2.0 cap awareness | `0.4.0` |
| **P5 — SolarEdge + future** | Real solar production sensor when API access regained; local EcoFlow BLE; multi-battery | `1.0.0` |

---

## 10b. Adversarial-review traceability

This spec was reviewed by two adversarial LLM reviewers (`minimax`, `gpt-5.5`) on 2026-05-03. Synthesis: `.adversarial-review/runs/2026-05-03-210543-plan/synthesis.md`. All 5 high and all 8 medium findings are addressed inline (see S1–S13 references throughout); 5 low and 1 nit also addressed (S14–S19). No findings deferred.

## 11. Out of scope

- HEMS-class control of HVAC compressor staging
- Whole-home transfer switch / critical-loads subpanel design (electrician work)
- NEM 3.0 / NBT economic modeling (only relevant if grandfathering ends)
- Multi-site / multi-account
- Mobile-app push notifications beyond HA's built-in notify

---

## 12. Open questions / TODO before implementation

1. Confirm Eagle 200 sign convention with a midday solar test (user action). Default to `rainforest_eagle` integration's documented semantics (positive = importing); flip via options if observed otherwise.
2. **Solar production sensor (P5 precondition):** Emporia solar 220V clamps currently read 0 (channels 5/7/8/10 unnamed). User to verify Emporia app config and expose as named entity. Until resolved, `sensor.power_control_solar_w` reports `unknown` and is **not used by battery logic** (charge logic uses Eagle `export_w`, see §6.1). Marked as P5 precondition in §10. (S5)
3. Decide EcoFlow Cloud HACS integration version pinning once Delta 3 Max arrives (Delta 3 Max support is recent; integration version matters).
4. **Holiday source pinned (S12):** `python-holidays>=0.50` with `country="US"`, supplemented by an explicit allowlist of holidays observed under PG&E E-TOU-D tariff Schedule. Library is updated annually; CI runs `python -c "import holidays; assert holidays.US(years=[CURRENT_YEAR])"` to fail fast if the package is removed.
5. **`climate.thermostat_2` resolution (S18):** Pre-P2 user action — confirm whether it is a stale duplicate (remove from HA) or a real second zone. v1 supports a single climate entity only; multi-zone deferred. If a real second zone exists, config flow warns and uses only the primary; `binary_sensor.power_control_climate_healthy` reflects only the primary zone. Multi-zone support is filed as a P5 candidate.

---

## 13. Acceptance criteria

- Integration installs from HACS on HA 2026.4+ without manifest errors.
- Config flow completes with current setup (battery absent) and integration runs in monitor-only mode.
- All declared entities register and report sane values.
- Mean-indoor-temp sensor responds to inclusion switches.
- Projected-true-up sensor reproduces every line item of `MarchBill.pdf` within $1 each and the cumulative balance within $5 (regression fixture; line items enumerated in §9.1 `test_trueup.py`).
- Dry-run logs show plausible decisions for ≥2 weeks before enabling live writes.
- After enabling climate override, precool triggers only when all conditions met; setpoint always reverts.
- Manual Ecobee touch disables override for ≥30 min.
- Unit + integration tests pass in CI.
