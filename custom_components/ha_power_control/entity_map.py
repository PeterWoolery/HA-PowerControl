"""Resolved-entity map and validation."""

from __future__ import annotations

from dataclasses import dataclass, field


class ValidationError(Exception):
    """Raised when an EntityMap fails basic validation."""


@dataclass
class EntityMap:
    net_w_entity: str
    net_import_kwh_entity: str
    net_export_kwh_entity: str
    climate_entity: str
    indoor_temp_entities: list[str]
    net_w_sign: int = 1
    solar_w_entity: str | None = None
    battery_soc_entity: str | None = None
    battery_charge_w_entity: str | None = None
    battery_discharge_w_entity: str | None = None
    battery_charge_switch_entity: str | None = None
    included_indoor_temps: dict[str, bool] = field(default_factory=dict)

    def validate_basic(self) -> None:
        """Validate domain prefixes and required fields. Raises ValidationError."""
        if self.net_w_sign not in (1, -1):
            raise ValidationError("net_w_sign must be +1 or -1")
        if not self.indoor_temp_entities:
            raise ValidationError("at least one indoor temperature sensor is required")
        if not self.climate_entity.startswith("climate."):
            raise ValidationError("climate entity must be in 'climate' domain")
        for eid in self.indoor_temp_entities:
            if not eid.startswith("sensor."):
                raise ValidationError(f"indoor temp {eid} must be in 'sensor' domain")
        for eid in (self.net_w_entity, self.net_import_kwh_entity, self.net_export_kwh_entity):
            if not eid.startswith("sensor."):
                raise ValidationError(f"net-meter entity {eid} must be in 'sensor' domain")

    def battery_present(self) -> bool:
        return self.battery_soc_entity is not None
