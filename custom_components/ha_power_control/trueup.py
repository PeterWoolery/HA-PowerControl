"""NEM 2.0 true-up projector — replicates PG&E E-TOU-D + SJCE bill line items.

All public functions are pure; no Home Assistant imports.

Formula notes (derived from MarchBill.pdf 2026-03-05 to 2026-04-02):
- PGE delivery charges apply to NET peak/off-peak usage
- NBC state-mandated charge applies to net usage (imports - exports)
- NBC net-usage adjustment credits gross exports at nbc_export_per_kwh
- Generation credit credits gross exports at nem_export_credit_per_kwh (NEM avoided-cost rate)
- PCIA applies to gross imports
- Franchise fee, SJ UUT, SJ franchise all apply to the pre-tax subtotal directly (no compounding)
"""

from __future__ import annotations

from dataclasses import dataclass

from .rates_loader import RateTable


@dataclass(frozen=True)
class BillingPeriod:
    billing_days: int
    net_peak_kwh: float
    net_off_peak_kwh: float
    imports_kwh: float
    exports_kwh: float

    @property
    def net_usage_kwh(self) -> float:
        return self.imports_kwh - self.exports_kwh


@dataclass(frozen=True)
class MonthlyNemCharges:
    pge_net_peak_charge: float
    pge_net_off_peak_charge: float
    nbc_net_usage_adjustment: float
    nbc_state_mandated: float
    generation_credit: float
    pcia: float
    franchise_fee_surcharge: float
    sj_uut: float
    sj_franchise_surcharge: float

    @property
    def total(self) -> float:
        return (
            self.pge_net_peak_charge
            + self.pge_net_off_peak_charge
            + self.nbc_net_usage_adjustment
            + self.nbc_state_mandated
            + self.generation_credit
            + self.pcia
            + self.franchise_fee_surcharge
            + self.sj_uut
            + self.sj_franchise_surcharge
        )


@dataclass(frozen=True)
class SjceCharges:
    peak_charge: float
    off_peak_charge: float
    local_uut: float
    energy_commission_surcharge: float

    @property
    def total(self) -> float:
        return (
            self.peak_charge
            + self.off_peak_charge
            + self.local_uut
            + self.energy_commission_surcharge
        )


def project_monthly_nem_charges(period: BillingPeriod, rt: RateTable) -> MonthlyNemCharges:
    # PGE delivery on net TOU usage
    pge_peak = period.net_peak_kwh * rt.pge_delivery_peak_per_kwh
    pge_off_peak = period.net_off_peak_kwh * rt.pge_delivery_off_peak_per_kwh

    # NBC non-bypassable: state-mandated on net usage, adjustment credits gross exports
    nbc_state_mandated = period.net_usage_kwh * rt.nbc_state_per_kwh
    nbc_net_usage_adjustment = -period.exports_kwh * rt.nbc_export_per_kwh

    # NEM 2.0 generation credit: exports credited at avoided-cost retail rate
    generation_credit = -period.exports_kwh * rt.nem_export_credit_per_kwh

    # PCIA on gross imports
    pcia = period.imports_kwh * rt.pcia_per_kwh

    # Pre-tax subtotal; taxes apply to this base directly (no compounding)
    pre_tax = (
        pge_peak
        + pge_off_peak
        + nbc_net_usage_adjustment
        + nbc_state_mandated
        + generation_credit
        + pcia
    )
    franchise_fee = max(pre_tax, 0) * rt.franchise_fee_pct
    sj_uut = max(pre_tax, 0) * rt.sj_utility_users_tax_pct
    sj_franchise = max(pre_tax, 0) * rt.sj_franchise_surcharge_pct

    return MonthlyNemCharges(
        pge_net_peak_charge=round(pge_peak, 2),
        pge_net_off_peak_charge=round(pge_off_peak, 2),
        nbc_net_usage_adjustment=round(nbc_net_usage_adjustment, 2),
        nbc_state_mandated=round(nbc_state_mandated, 2),
        generation_credit=round(generation_credit, 2),
        pcia=round(pcia, 2),
        franchise_fee_surcharge=round(franchise_fee, 2),
        sj_uut=round(sj_uut, 2),
        sj_franchise_surcharge=round(sj_franchise, 2),
    )


def project_sjce_charges(period: BillingPeriod, rt: RateTable) -> SjceCharges:
    peak_charge = period.net_peak_kwh * rt.sjce_peak_per_kwh
    off_peak_charge = period.net_off_peak_kwh * rt.sjce_off_peak_per_kwh
    sub = peak_charge + off_peak_charge
    local_uut = max(sub, 0) * rt.sjce_local_uut_pct
    ecs = period.imports_kwh * rt.energy_commission_surcharge_per_kwh

    return SjceCharges(
        peak_charge=round(peak_charge, 2),
        off_peak_charge=round(off_peak_charge, 2),
        local_uut=round(local_uut, 2),
        energy_commission_surcharge=round(ecs, 2),
    )
