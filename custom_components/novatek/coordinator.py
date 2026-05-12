"""DataUpdateCoordinator for the Novatek integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NovatekAuthError, NovatekClient, NovatekConnectionError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class NovatekCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll a Novatek device at a fixed interval and surface parsed readings."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: NovatekClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({client.host})",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_data()
        except NovatekAuthError as err:
            # Auth failures should not be retried silently.
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except NovatekConnectionError as err:
            raise UpdateFailed(f"Error communicating with Novatek device: {err}") from err
