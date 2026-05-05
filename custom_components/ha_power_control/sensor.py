"""Sensor platform: net_w, export_w, solar_w, mean_indoor_temp, in_peak_window, etc."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HAPowerControlCoordinator
from .models import PowerState
from .rates_loader import load_rate_table
from .trueup import BillingPeriod, project_monthly_nem_charges


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: HAPowerControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            NetWSensor(coord),
            ExportWSensor(coord),
            SolarWSensor(coord),
            MeanIndoorTempSensor(coord),
            BatterySocSensor(coord),
            ProjectedTrueupSensor(coord),
            TodayPeakSavingsSensor(coord),
        ]
    )


class _Base(CoordinatorEntity[HAPowerControlCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord: HAPowerControlCoordinator, key: str, name: str) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{coord.entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coord.entry.entry_id)},
            name="HA Power Control",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def state_obj(self) -> PowerState | None:
        return self.coordinator.data


class NetWSensor(_Base):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord):
        super().__init__(coord, "net_w", "Net Power")

    @property
    def native_value(self):
        return self.state_obj.net_w if self.state_obj else None


class ExportWSensor(_Base):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord):
        super().__init__(coord, "export_w", "Export Power")

    @property
    def native_value(self):
        return self.state_obj.export_w if self.state_obj else None


class SolarWSensor(_Base):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord):
        super().__init__(coord, "solar_w", "Solar Power")

    @property
    def native_value(self):
        return self.state_obj.solar_w if self.state_obj else None


class MeanIndoorTempSensor(_Base):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = "°F"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord):
        super().__init__(coord, "mean_indoor_f", "Mean Indoor Temperature")

    @property
    def native_value(self):
        return self.state_obj.mean_indoor_f if self.state_obj else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.state_obj is None:
            return {}
        return {"included_temps": self.state_obj.indoor_temps}


class BatterySocSensor(_Base):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord):
        super().__init__(coord, "battery_soc", "Battery SoC")

    @property
    def native_value(self):
        if self.state_obj and self.state_obj.battery:
            return self.state_obj.battery.soc_pct
        return None


class ProjectedTrueupSensor(_Base):
    _attr_native_unit_of_measurement = "USD"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord):
        super().__init__(coord, "projected_trueup", "Projected True-Up")

    @property
    def native_value(self):
        # P1: project current period's charges only; full YTD projection is a P4 enhancement.
        if self.state_obj is None:
            return None
        rt = load_rate_table()
        # Approx period using today's totals; refined when recorder integration lands in P4.
        period = BillingPeriod(
            billing_days=1,
            net_peak_kwh=self.state_obj.today_kwh_imported * 0.2,
            net_off_peak_kwh=self.state_obj.today_kwh_imported * 0.8,
            imports_kwh=self.state_obj.today_kwh_imported,
            exports_kwh=self.state_obj.today_kwh_exported,
        )
        return round(project_monthly_nem_charges(period, rt).total, 2)


class TodayPeakSavingsSensor(_Base):
    _attr_native_unit_of_measurement = "USD"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coord):
        super().__init__(coord, "today_peak_savings", "Today's Peak Savings")

    @property
    def native_value(self):
        return self.state_obj.today_peak_savings_usd if self.state_obj else 0.0
