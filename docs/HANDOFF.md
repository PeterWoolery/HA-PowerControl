# HA Power Control — Session Handoff

**Last updated:** 2026-05-06
**Status:** P1 shipped; ready for P2 planning.

---

## Where we are

**v0.1.0** is tagged locally at commit `a933fff`. P1 (acquisition + monitoring + true-up + dashboard) is fully implemented:

- 77/77 tests passing, 95.18% line coverage, ruff clean
- HACS-installable custom integration in `custom_components/ha_power_control/`
- All 6 platforms wired (sensor, binary_sensor, switch, number, select, button)
- Reference Lovelace dashboard + in-repo validator
- Live-smoke REST harness at `scripts/live_smoke.py`
- GitHub Actions CI at `.github/workflows/ci.yml`

**No code is running on the live HA instance yet.** The integration has not been manually installed on `192.168.1.103` — that's a recommended next step before P2 begins.

## Repo orientation (start here)

| File | Purpose |
|---|---|
| `docs/superpowers/specs/2026-05-03-ha-power-control-design.md` | Full design spec — adversarial-reviewed, 19 findings addressed |
| `docs/superpowers/plans/2026-05-03-ha-power-control-p1.md` | P1 plan with execution-status header (all ✅) |
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

## P2 — what's next

**Goal:** Climate controller — precool before peak with excess solar, hold at peak ceiling during 5-8pm M-F.

**Spec section to plan against:** `docs/superpowers/specs/2026-05-03-ha-power-control-design.md` §6.3 (climate controller).

**Approach for the next session:**

1. Use `superpowers:writing-plans` skill against the spec's §6.3 to produce `docs/superpowers/plans/2026-05-06-ha-power-control-p2.md`.
2. P2 implementation will live in a new `policy/climate.py` module (currently the `policy/` directory is empty — spec expects it).
3. P2 needs:
   - Persistence of original `target_temp_high` via `HAPowerControlStore` (already in repo, currently unused beyond P1 stub).
   - `async_track_point_in_time` anchored to peak start.
   - `dry_run` switch (already exists from T14) gates whether climate writes actually fire.
   - Restoration logic with crash-safe `precool_ran_this_cycle` flag (spec §6.3).
   - `owns_climate` binary sensor (already exists from T13) updates when controller takes over.
4. New tests should cover: precool entry/exit, peak-hold entry/exit, restoration after crash mid-cycle, user-override detection (if user changes setpoint manually, controller backs off).

**Out of scope for P2** (deferred): battery state machine (P3 — waits for Delta 3 Max delivery), ROI recommender (P4), multi-zone (P5).

## How to resume

1. Open a fresh Claude session in `/home/peter/Projects/HA-PowerControl/`.
2. Point it at this handoff doc.
3. Run the writing-plans skill against the design spec to produce the P2 plan.
4. Optionally manually install v0.1.0 on the live HA (192.168.1.103) and run `scripts/live_smoke.py` to verify entities populate before starting P2.
5. Then dispatch subagent-driven-development against the P2 plan.

## Open questions for the user (carry into next session)

- Should v0.1.0 be installed on the live HA before P2 begins, or should P2 ship as v0.2.0 in one cut?
- Is the user OK with the P2 implementer making HA `climate.set_temperature` service calls in dry_run=False mode against the live thermostat during testing? (Spec says yes with confirm-once UX, but worth re-confirming.)
- Confirm peak window (17:00–20:00 M-F, US holidays observed) is still the operating policy — no recent PG&E rate plan changes the user is aware of.
