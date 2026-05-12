"""Constants for the Novatek integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "novatek"

# Options key
CONF_SCAN_INTERVAL: Final = "scan_interval"

# Defaults
DEFAULT_PORT: Final = 80
DEFAULT_SCAN_INTERVAL: Final = 5  # seconds
DEFAULT_TIMEOUT: Final = 10  # seconds for HTTP requests

# Canonical data keys returned by NovatekClient.async_get_data().
# Keep these stable — sensor.py depends on them.
KEY_VOLTAGE: Final = "voltage"
KEY_CURRENT: Final = "current"
KEY_FREQUENCY: Final = "frequency"
KEY_ACTIVE_POWER: Final = "active_power"
KEY_APPARENT_POWER: Final = "apparent_power"
KEY_ENERGY_TOTAL: Final = "energy_total"          # active energy, Wh
KEY_APPARENT_ENERGY: Final = "apparent_energy"    # apparent energy, VAh

# Device identity
KEY_SERIAL: Final = "serial"
KEY_FIRMWARE: Final = "firmware"
KEY_MODEL: Final = "model"

MANUFACTURER: Final = "Novatek-Electro"
MODEL: Final = "Novatek"
