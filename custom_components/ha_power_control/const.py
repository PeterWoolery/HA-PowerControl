"""Constants for HA Power Control."""
from __future__ import annotations

DOMAIN = "ha_power_control"
PLATFORMS = ["sensor", "binary_sensor", "switch", "number", "select", "button"]

# Coordinator
DEFAULT_UPDATE_INTERVAL_S = 30

# E-TOU-D tariff
PEAK_HOUR_START = 17  # 5pm local
PEAK_HOUR_END = 20    # 8pm local
PEAK_DAYS = (0, 1, 2, 3, 4)  # Mon-Fri (datetime.weekday())

# Defaults for number/select entities
DEFAULTS = {
    "battery_reserve_pct": 20.0,
    "max_charge_w": 1200.0,
    "precool_offset_f": 4.0,
    "peak_max_temp_f": 80.0,
    "min_cool_f": 65.0,
    "max_cool_f": 82.0,
    "charge_threshold_w": 200.0,
    "min_charge_w": 50.0,
    "charge_buffer_w": 100.0,
    "discharge_min_import_w": 100.0,
    "force_override_min": 60,
    "cooldown_min": 30,
    "drift_tolerance_f": 0.5,
    "drift_grace_s": 60,
    "sleep_start_h": 22,
    "sleep_end_h": 6,
    "trueup_month": 6,  # June
    "operating_mode": "auto",
    "climate_preset_target": "home",
    "dry_run": True,  # ship as opt-in
    "climate_override_enabled": False,
}

# Config-flow keys
CONF_NET_W = "net_w_entity"
CONF_NET_IMPORT_KWH = "net_import_kwh_entity"
CONF_NET_EXPORT_KWH = "net_export_kwh_entity"
CONF_SOLAR_W = "solar_w_entity"
CONF_CLIMATE = "climate_entity"
CONF_INDOOR_TEMPS = "indoor_temp_entities"
CONF_BATTERY_SOC = "battery_soc_entity"
CONF_BATTERY_CHARGE_W = "battery_charge_w_entity"
CONF_BATTERY_DISCHARGE_W = "battery_discharge_w_entity"
CONF_BATTERY_CHARGE_SWITCH = "battery_charge_switch_entity"
CONF_NET_W_SIGN = "net_w_sign"
CONF_TRUEUP_MONTH = "trueup_month"

# Modes
MODE_AUTO = "auto"
MODE_PEAK_SHAVE_ONLY = "peak_shave_only"
MODE_CHARGE_ONLY = "charge_only"
MODE_OFF = "off"
MODES = [MODE_AUTO, MODE_PEAK_SHAVE_ONLY, MODE_CHARGE_ONLY, MODE_OFF]

# Storage keys
STORE_KEY = f"{DOMAIN}.climate_state"
STORE_VERSION = 1
