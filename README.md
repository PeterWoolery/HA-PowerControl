# HA Power Control

Home Assistant custom integration that orchestrates rooftop solar, an EcoFlow Delta 3 Max battery (pass-through UPS, P3), and an Ecobee thermostat (P2) under a NEM 2.0 / E-TOU-D tariff.

**Phase 1 (this release):** read-only monitoring, mean-indoor-temperature with selectable inclusion, projected NEM 2.0 true-up balance, dashboard.

## Honest economics under NEM 2.0

This integration's recommender will tell you, accurately, that **adding battery capacity does not pay back its capex on cycle arbitrage** under NEM 2.0 + E-TOU-D. The peak/off-peak retail delta is ~$0.07/kWh, and round-trip storage losses consume nearly all of it because exporting the same kWh would have credited at the same retail rate. Real value of storage is **backup readiness**, **NEM-vintage hedging**, **comfort optimization**, and **load-shift behavior changes** — see the recommender output for the full breakdown.

## Install (HACS)

1. HACS → Integrations → Custom repositories → add this repo, type "Integration".
2. Install → restart Home Assistant.
3. Settings → Devices & Services → Add Integration → "HA Power Control".
4. Pick your Eagle 200, Ecobee, indoor temp sensors, and (optional) battery entities.

## Dashboard

Copy `custom_components/ha_power_control/lovelace/dashboard.yaml` into a new Lovelace dashboard or merge into an existing one.

## P2 — Climate Controller (v0.2.0)

When excess solar is available, HA Power Control precools the house before the 5–8pm peak window and holds the thermostat at a configurable ceiling during peak hours.

**Behavior:**
- **Precool (before peak)**: when net export ≥ 200 W has been sustained for ≥10 minutes and peak begins within the precool lookahead window, the integration lowers `target_temp_high` by `precool_offset_f` (default 2 °F) and captures the original setpoint for restoration.
- **Peak hold**: at peak start, `target_temp_high` is clamped to `peak_max_temp_f` (default 76 °F) for the duration of the peak window (17:00–20:00 M–F, US holidays observed).
- **Restoration**: at peak end, the original setpoint is restored automatically. If indoor temperature exceeds `peak_max_temp_f` during peak hold, the controller aborts hold and restores originals so the AC can run.
- All cycle state persists across HA restarts; the integration restores originals automatically on startup if a cycle was interrupted.

**New entities (P2):**
| Entity | Kind | Description |
|---|---|---|
| `switch.dry_run` | switch | When on (default), policy decisions are logged but no `climate.set_temperature` calls fire. |
| `switch.climate_override_enabled` | switch | Master enable for climate writes. Must be on alongside dry_run=off. |
| `binary_sensor.owns_climate` | binary_sensor | On when the controller holds ownership of the thermostat (precool or peak-hold active). |
| `number.precool_offset_f` | number | How many °F to drop the setpoint during precool (default 2). |

**Safety:**
- Default is `dry_run=on` and `climate_override_enabled=off`. Both must be flipped explicitly to enable writes.
- Setpoint writes are clamped to `[min_cool_f, max_cool_f]` defensively.
- The integration only writes `target_temp_high`. It NEVER touches `target_temp_low`, so the heat threshold is preserved.
- External-override detection: if the user manually changes the setpoint during a controller-owned cycle, the controller backs off with a configurable cooldown.

**Not yet implemented (deferred from P2 scope):**
- Mode A preset maintenance — the integration does not yet enforce a preset target outside the precool/peak-hold windows.

**Enable on live HA:**
1. Toggle `switch.dry_run` → off.
2. Toggle `switch.climate_override_enabled` → on.
3. Watch `binary_sensor.owns_climate` — flips on when the controller takes ownership.

## Phase roadmap

| Phase | Status | Scope |
|---|---|---|
| P1 | ✅ v0.1.0 | Acquisition + monitoring + true-up projector + dashboard |
| P2 | ✅ v0.2.0 | Ecobee precool / peak-hold controller |
| P3 | Next — pending Delta 3 Max delivery | Battery charge/discharge state machine |
| P4 | Planned | ROI / sizing recommender |
| P5 | When SolarEdge API access is available | Real solar production sensor, multi-zone climate |

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check .
```

## References

- Spec: `docs/superpowers/specs/`
- Plan: `docs/superpowers/plans/2026-05-03-ha-power-control-p1.md`
- Live smoke harness: `scripts/live_smoke.py`

License: MIT.
