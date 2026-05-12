"""Sensor entities for the Novatek integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    KEY_ACTIVE_POWER,
    KEY_APPARENT_ENERGY,
    KEY_APPARENT_POWER,
    KEY_CURRENT,
    KEY_ENERGY_TOTAL,
    KEY_FIRMWARE,
    KEY_FREQUENCY,
    KEY_MODEL,
    KEY_SERIAL,
    KEY_VOLTAGE,
    MANUFACTURER,
    MODEL,
)
from .coordinator import NovatekCoordinator


@dataclass(frozen=True, kw_only=True)
class NovatekSensorDescription(SensorEntityDescription):
    """Description of a Novatek sensor + how to extract its value."""

    value_fn: Callable[[dict[str, Any]], Any]


def _get(key: str) -> Callable[[dict[str, Any]], Any]:
    return lambda data: data.get(key)


SENSOR_DESCRIPTIONS: tuple[NovatekSensorDescription, ...] = (
    NovatekSensorDescription(
        key=KEY_VOLTAGE,
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_get(KEY_VOLTAGE),
    ),
    NovatekSensorDescription(
        key=KEY_CURRENT,
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_get(KEY_CURRENT),
    ),
    NovatekSensorDescription(
        key=KEY_FREQUENCY,
        translation_key="frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_get(KEY_FREQUENCY),
    ),
    NovatekSensorDescription(
        key=KEY_ACTIVE_POWER,
        translation_key="active_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_get(KEY_ACTIVE_POWER),
    ),
    NovatekSensorDescription(
        key=KEY_APPARENT_POWER,
        translation_key="apparent_power",
        device_class=SensorDeviceClass.APPARENT_POWER,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_get(KEY_APPARENT_POWER),
    ),
    # Active energy is in Wh from the device; HA's Energy dashboard accepts
    # any energy unit + total_increasing and will display in kWh.
    NovatekSensorDescription(
        key=KEY_ENERGY_TOTAL,
        translation_key="energy_total",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=_get(KEY_ENERGY_TOTAL),
    ),
    NovatekSensorDescription(
        key=KEY_APPARENT_ENERGY,
        translation_key="apparent_energy",
        # HA doesn't have a dedicated apparent-energy device class; expose
        # the raw VAh value with no device_class so it stays a plain sensor.
        native_unit_of_measurement="VAh",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=_get(KEY_APPARENT_ENERGY),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Novatek sensors from a config entry."""
    coordinator: NovatekCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        NovatekSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)


class NovatekSensor(CoordinatorEntity[NovatekCoordinator], SensorEntity):
    """A single sensor reading from the Novatek device."""

    _attr_has_entity_name = True
    entity_description: NovatekSensorDescription

    def __init__(
        self,
        coordinator: NovatekCoordinator,
        entry: ConfigEntry,
        description: NovatekSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description

        data = coordinator.data or {}
        serial = data.get(KEY_SERIAL) or entry.unique_id or entry.entry_id
        model = data.get(KEY_MODEL) or MODEL

        self._attr_unique_id = f"{serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(serial))},
            manufacturer=MANUFACTURER,
            model=model,
            name=entry.title,
            sw_version=data.get(KEY_FIRMWARE),
            configuration_url=f"http://{coordinator.client.host}",
        )

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        return self.entity_description.value_fn(data)

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        data = self.coordinator.data or {}
        return self.entity_description.value_fn(data) is not None
