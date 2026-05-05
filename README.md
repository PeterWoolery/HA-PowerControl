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

## Phase roadmap

| Phase | Status | Scope |
|---|---|---|
| P1 | This release | Acquisition + monitoring + true-up projector + dashboard |
| P2 | Planned | Ecobee precool / peak-hold controller |
| P3 | After Delta 3 Max ships | Battery charge/discharge state machine |
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
