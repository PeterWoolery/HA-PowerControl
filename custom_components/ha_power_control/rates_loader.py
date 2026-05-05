"""Load E-TOU-D + SJCE rate tables from versioned YAML fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

_RATES_DIR = Path(__file__).parent / "rates"


@dataclass(frozen=True)
class RateTable:
    schedule: str
    effective_from: date
    base_services_charge_per_day: float
    pge_delivery_peak_per_kwh: float
    pge_delivery_off_peak_per_kwh: float
    sjce_peak_per_kwh: float
    sjce_off_peak_per_kwh: float
    # NBC non-bypassable charges split:
    # nbc_state_per_kwh applied to net usage; nbc_export_per_kwh applied to gross exports
    nbc_state_per_kwh: float
    nbc_export_per_kwh: float
    # NEM 2.0 export credit at avoided-cost retail rate
    nem_export_credit_per_kwh: float
    pcia_per_kwh: float
    franchise_fee_pct: float
    sj_utility_users_tax_pct: float
    sj_franchise_surcharge_pct: float
    sjce_local_uut_pct: float
    energy_commission_surcharge_per_kwh: float
    trueup_month: int

    @property
    def combined_peak_per_kwh(self) -> float:
        return self.pge_delivery_peak_per_kwh + self.sjce_peak_per_kwh

    @property
    def combined_off_peak_per_kwh(self) -> float:
        return self.pge_delivery_off_peak_per_kwh + self.sjce_off_peak_per_kwh


def _parse(raw: dict) -> RateTable:
    return RateTable(
        schedule=raw["schedule"],
        effective_from=date.fromisoformat(str(raw["effective_from"])),
        base_services_charge_per_day=float(raw["base_services_charge_per_day"]),
        pge_delivery_peak_per_kwh=float(raw["pge_delivery"]["peak_per_kwh"]),
        pge_delivery_off_peak_per_kwh=float(raw["pge_delivery"]["off_peak_per_kwh"]),
        sjce_peak_per_kwh=float(raw["sjce_generation"]["peak_per_kwh"]),
        sjce_off_peak_per_kwh=float(raw["sjce_generation"]["off_peak_per_kwh"]),
        nbc_state_per_kwh=float(raw["nbc_state_per_kwh"]),
        nbc_export_per_kwh=float(raw["nbc_export_per_kwh"]),
        nem_export_credit_per_kwh=float(raw["nem_export_credit_per_kwh"]),
        pcia_per_kwh=float(raw["pcia_2018_vintage_per_kwh"]),
        franchise_fee_pct=float(raw["franchise_fee_pct"]),
        sj_utility_users_tax_pct=float(raw["sj_utility_users_tax_pct"]),
        sj_franchise_surcharge_pct=float(raw["sj_franchise_surcharge_pct"]),
        sjce_local_uut_pct=float(raw["sjce_local_uut_pct"]),
        energy_commission_surcharge_per_kwh=float(raw["energy_commission_surcharge_per_kwh"]),
        trueup_month=int(raw["trueup_month"]),
    )


def load_rate_table(as_of: date | None = None) -> RateTable:
    """Load the latest rate table whose effective_from <= as_of (default today)."""
    candidates = []
    for f in _RATES_DIR.glob("*.yaml"):
        with f.open() as fh:
            data = yaml.safe_load(fh)
        rt = _parse(data)
        candidates.append(rt)
    if not candidates:
        raise FileNotFoundError(f"No rate tables found in {_RATES_DIR}")
    if as_of is None:
        as_of = date.today()
    eligible = [c for c in candidates if c.effective_from <= as_of]
    if not eligible:
        return min(candidates, key=lambda c: c.effective_from)
    return max(eligible, key=lambda c: c.effective_from)
