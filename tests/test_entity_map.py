"""Tests for entity-map validation."""

from __future__ import annotations

import pytest

from custom_components.ha_power_control.entity_map import EntityMap, ValidationError


def test_entity_map_valid_minimal() -> None:
    em = EntityMap(
        net_w_entity="sensor.eagle_200_meter_power_demand",
        net_import_kwh_entity="sensor.eagle_200_total_meter_energy_delivered",
        net_export_kwh_entity="sensor.eagle_200_total_meter_energy_received",
        climate_entity="climate.thermostat",
        indoor_temp_entities=["sensor.bedroom_temperature"],
        net_w_sign=1,
    )
    em.validate_basic()  # should not raise


def test_entity_map_missing_indoor_temps_raises() -> None:
    em = EntityMap(
        net_w_entity="sensor.x",
        net_import_kwh_entity="sensor.y",
        net_export_kwh_entity="sensor.z",
        climate_entity="climate.t",
        indoor_temp_entities=[],
        net_w_sign=1,
    )
    with pytest.raises(ValidationError, match="at least one indoor temperature"):
        em.validate_basic()


def test_entity_map_wrong_climate_domain_raises() -> None:
    em = EntityMap(
        net_w_entity="sensor.x",
        net_import_kwh_entity="sensor.y",
        net_export_kwh_entity="sensor.z",
        climate_entity="sensor.notaclimate",
        indoor_temp_entities=["sensor.t"],
        net_w_sign=1,
    )
    with pytest.raises(ValidationError, match="climate entity must be in 'climate' domain"):
        em.validate_basic()


def test_entity_map_invalid_sign_raises() -> None:
    em = EntityMap(
        net_w_entity="sensor.x",
        net_import_kwh_entity="sensor.y",
        net_export_kwh_entity="sensor.z",
        climate_entity="climate.t",
        indoor_temp_entities=["sensor.t"],
        net_w_sign=0,
    )
    with pytest.raises(ValidationError, match="net_w_sign must be \\+1 or -1"):
        em.validate_basic()
