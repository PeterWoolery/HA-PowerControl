# HA Power Control — Session Handoff

**Last updated:** 2026-05-07
**Status:** P2 shipped (v0.2.0); ready for P3 planning once Delta 3 Max arrives.

---

## Where we are

**v0.2.0** is tagged locally. P2 (climate controller — precool + peak-hold) is fully implemented on top of P1:

- 110/110 tests passing, ≥85% line coverage, ruff clean
- HACS-installable custom integration in `custom_components/ha_power_control/`
- All 6 platforms wired (sensor, binary_sensor, switch, number, select, button)
- Climate policy: pure-Python `policy/climate.py` + async `policy/climate_runner.py`
- Crash-safe cycle state via `HAPowerControlStore`
- Reference Lovelace dashboard + in-repo validator
- Live-smoke REST harness at `scripts/live_smoke.py`
- GitHub Actions CI at `.github/workflows/ci.yml`

**No code is running on the live HA instance yet.** The integration has not been manually installed on `192.168.1.103` — that's a recommended next step before P3 planning begins.

## Repo orientation (start here)

| File | Purpose |
|---|---|
| `docs/superpowers/specs/2026-05-03-ha-power-control-design.md` | Full design spec — adversarial-reviewed, 19 findings addressed |
| `docs/superpowers/plans/2026-05-03-ha-power-control-p1.md` | P1 plan with execution-status header (all ✅) |
| `docs/superpowers/plans/2026-05-06-ha-power-control-p2.md` | P2 plan with execution-status header (all 16 tasks ✅) |
| `README.md` | User-facing install + roadmap |
| `tests/fixtures/march_bill_2026.json` | Sanitized PG&E bill for true-up regression tests |
| `custom_components/ha_power_control/rates/etoud_2026-03-01.yaml` | Rate table tuned to within $1/line of MarchBill.pdf |

## Critical context the next agent needs

1. **Package name is `holidays`**, not `python-holidays`. The PyPI package and the import are both `holidays`. The spec/plan got this wrong originally; manifest.json and pyproject.toml are correct.

2. **NEM 2.0 economics are honest, not hyped.** Storage saves ~$0.005/kWh (not $0.07) because exports forfeit retail TOU credits. Real value: backup, hedge, comfort, behavioral load-shift. P4 recommender emits multi-row output framing battery payback against the full case for ownership. Don't let any new code re-introduce the "$0.07/kWh arbitrage" narrative.

3. **Trueup YAML schema** was extended beyond the spec: `nbc_state_per_kwh`, `nbc_export_per_kwh`, `nem_export_credit_per_kwh` (split from spec's single `nbc_per_kwh`). `RateTable` and `_parse` reflect this — see `rates_loader.py`.

4. **Climate setpoint inversion safety:** P2 must ONLY manipulate `target_temp_high` (cooling threshold) on the `heat_cool` thermostat. NEVER touch `target_temp_low` — that would activate the furnace. This is enforced in the design spec §6.3 and must carry into P2 implementation.

5. **`tests/conftest.py` strips an editable-install `PATH_PLACEHOLDER`** from `custom_components.__path__` before HA's loader runs. Don't remove this — `pytest-homeassistant-custom-component` chokes without it.

6. **`OptionsFlow.__init__` should NOT set `self.config_entry`.** Modern HA provides it via a property; setting it triggers `report_usage` warnings (breaks in 2025.12).

7. **Unit normalization**: `coordinator._normalize_kw_to_w` converts kW→W based on `unit_of_measurement` attribute. Eagle 200 reports kW; some devices report W. Don't assume.

## P2 complete

**v0.2.0** is tagged locally. P2 (climate controller — precool + peak-hold) is fully implemented:

- 110/110 tests passing, ≥85% coverage, ruff clean
- Pure-policy `policy/climate.py` with `decide()` + `ClimateInputs` / `Action` types
- Async runner `policy/climate_runner.py` with dry-run gate
- Coordinator-driven tick: sustained-export tracking → precool entry → peak-hold → restoration
- Crash-safe: all cycle state in `HAPowerControlStore`; originals restored on startup
- External-override detection with configurable cooldown
- Safety bounds clamp on every setpoint write
- New entities: `switch.dry_run`, `switch.climate_override_enabled`, `binary_sensor.owns_climate`, `number.precool_offset_f`
- See `docs/superpowers/plans/2026-05-06-ha-power-control-p2.md` (execution-status header lists all 16 tasks ✅)

## P3 — what's next

**Goal:** Battery charge/discharge state machine (EcoFlow Delta 3 Max).

**Spec section to plan against:** `docs/superpowers/specs/2026-05-03-ha-power-control-design.md` §6.1 (battery state machine).

**Prerequisite:** Delta 3 Max hardware delivery. Do not begin P3 planning until the device is physically available and paired to Home Assistant.

**Approach for the next session:**

1. Confirm Delta 3 Max is connected and entities are visible in HA.
2. Run `scripts/live_smoke.py` against the live HA to verify all P2 entities (including `binary_sensor.owns_climate`) populate correctly.
3. Use `superpowers:writing-plans` skill against spec §6.1 to produce `docs/superpowers/plans/YYYY-MM-DD-ha-power-control-p3.md`.
4. Dispatch subagent-driven-development against the P3 plan.

**Out of scope for P3** (deferred): ROI recommender (P4), multi-zone climate (P5).

## How to resume

1. Open a fresh Claude session in `/home/peter/Projects/HA-PowerControl/`.
2. Point it at this handoff doc.
3. Confirm Delta 3 Max is available; if not, P3 is blocked — consider installing v0.2.0 on live HA and observing P2 behavior instead.
4. Run `scripts/live_smoke.py` to verify P2 entities on `192.168.1.103`.

## Open questions for the user (carry into next session)

- Has the Delta 3 Max been delivered and connected to HA?
- After live install of v0.2.0, do you want a smoke-test session to observe precool/peak-hold behavior before P3 begins?
- Confirm peak window (17:00–20:00 M-F, US holidays observed) is still the operating policy — no recent PG&E rate plan changes?
