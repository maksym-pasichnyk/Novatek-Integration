"""Config flow for the Novatek integration.

Two ways to add a device:
    * **DHCP discovery** — when HA notices a compatible Novatek device joining the LAN, it
        invokes ``async_step_dhcp``. The user only has to enter the password.
    * **Add integration** — the user opens the integration manually and we
        actively probe the local subnet, showing only discovered devices that are
        not already configured.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import dhcp
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .api import NovatekAuthError, NovatekClient, NovatekConnectionError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    KEY_MODEL,
    KEY_SERIAL,
)
from .discover import async_scan_for_novatek

_LOGGER = logging.getLogger(__name__)

PASSWORD_ONLY_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Authenticate with the device and return identity info."""
    session = async_get_clientsession(hass)
    client = NovatekClient(
        session,
        host=data[CONF_HOST],
        password=data[CONF_PASSWORD],
        port=data.get(CONF_PORT, DEFAULT_PORT),
    )
    readings = await client.async_test_connection()
    serial = readings.get(KEY_SERIAL) or data[CONF_HOST]
    model = readings.get(KEY_MODEL) or "Novatek"
    return {
        "title": f"{model} ({data[CONF_HOST]})",
        "fallback_unique_id": str(serial),
    }


class NovatekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Novatek."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_host: str | None = None
        self._scan_results: dict[str, dict[str, Any]] = {}

    # ----------------------------------------------------------- entry points

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show discovered, not-yet-configured devices when the user adds Novatek."""
        if not self._scan_results:
            session = async_get_clientsession(self.hass)
            results = await async_scan_for_novatek(self.hass, session)
            configured_hosts = {
                entry.data[CONF_HOST]
                for entry in self._async_current_entries()
                if CONF_HOST in entry.data
            }
            self._scan_results = {
                result["ip"]: result
                for result in results
                if result["ip"] not in configured_hosts
            }
            if not self._scan_results:
                return self.async_abort(reason="no_devices_found")

        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            return await self._async_finalise(data, errors, on_error_step="user")

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_discovered_device_schema(),
            errors=errors,
        )

    async def async_step_dhcp(
        self, discovery_info: dhcp.DhcpServiceInfo
    ) -> FlowResult:
        """Handle a DHCP-pushed discovery: device just joined the network."""
        unique_id = format_mac(discovery_info.macaddress)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info.ip}
        )
        self._discovered_host = discovery_info.ip
        self.context["title_placeholders"] = {
            "host": discovery_info.ip,
            "hostname": discovery_info.hostname or "Novatek",
        }
        return await self.async_step_discovery_confirm()

    # --------------------------------------------------------------- branches

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """After DHCP discovery, ask only for the device password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._discovered_host is not None
            data = {
                CONF_HOST: self._discovered_host,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            return await self._async_finalise(
                data, errors, on_error_step="discovery_confirm"
            )

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=PASSWORD_ONLY_SCHEMA,
            errors=errors,
            description_placeholders={"host": self._discovered_host or "?"},
        )

    # ---------------------------------------------------------------- finalise

    async def _async_finalise(
        self,
        data: dict[str, Any],
        errors: dict[str, str],
        *,
        on_error_step: str,
    ) -> FlowResult:
        """Validate against the device and create the config entry."""
        try:
            info = await _validate_input(self.hass, data)
        except NovatekAuthError:
            errors["base"] = "invalid_auth"
        except NovatekConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Novatek device")
            errors["base"] = "unknown"
        else:
            # If DHCP set a MAC-based unique_id, prefer that — it's stable
            # across DHCP-assigned IP changes. Otherwise fall back to the
            # serial-or-host string from the API.
            if not self.unique_id:
                await self.async_set_unique_id(info["fallback_unique_id"])
            self._abort_if_unique_id_configured(updates=data)
            return self.async_create_entry(title=info["title"], data=data)

        # Validation failed — re-render the originating step.
        if on_error_step == "user":
            return self.async_show_form(
                step_id="user",
                data_schema=self._build_discovered_device_schema(),
                errors=errors,
            )
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=PASSWORD_ONLY_SCHEMA,
            errors=errors,
            description_placeholders={"host": self._discovered_host or "?"},
        )

    def _build_discovered_device_schema(self) -> vol.Schema:
        """Build the form schema for discovered devices available to add."""
        choices = {
            ip: f"{result['model']} — {ip}"
            for ip, result in self._scan_results.items()
        }
        return vol.Schema(
            {
                vol.Required(CONF_HOST): vol.In(choices),
                vol.Required(CONF_PASSWORD): str,
            }
        )

    # ----------------------------------------------------------------- options

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NovatekOptionsFlow:
        return NovatekOptionsFlow(config_entry)


class NovatekOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to tweak polling interval after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=3600)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
