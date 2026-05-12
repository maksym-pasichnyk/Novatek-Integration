"""Active LAN scanner for Novatek power meters.

Used by the config flow when the user adds the integration manually and
DHCP-based discovery has not already surfaced the device.

We pull the local subnet(s) from ``homeassistant.components.network``,
fan out short-timeout HTTP probes to every host address, and keep the
ones that respond with a known Novatek ``device_info`` payload.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import Any

import aiohttp
from aiohttp import ClientError

from homeassistant.components import network
from homeassistant.core import HomeAssistant

from .api import DEVICE_MODELS

_LOGGER = logging.getLogger(__name__)

# Don't try to scan subnets larger than this. /22 = 1022 hosts; anything
# bigger usually means a strange / corporate setup we shouldn't pummel.
_MAX_SCAN_HOSTS = 1024


async def async_get_local_subnets(hass: HomeAssistant) -> list[ipaddress.IPv4Network]:
    """Return the IPv4 subnets HA's host considers 'local'."""
    subnets: list[ipaddress.IPv4Network] = []
    for adapter in await network.async_get_adapters(hass):
        if not adapter.get("enabled"):
            continue
        for v4 in adapter.get("ipv4", []):
            addr = v4.get("address")
            prefix = v4.get("network_prefix")
            if not addr or prefix is None:
                continue
            try:
                net = ipaddress.IPv4Network(f"{addr}/{prefix}", strict=False)
            except ValueError:
                continue
            if net.is_loopback or net.is_link_local or net.is_multicast:
                continue
            if net.num_addresses > _MAX_SCAN_HOSTS:
                _LOGGER.debug("Skipping subnet %s — too large to scan", net)
                continue
            subnets.append(net)
    return subnets


async def async_scan_for_novatek(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    *,
    concurrency: int = 48,
    timeout: float = 1.5,
) -> list[dict[str, Any]]:
    """Probe every host on each local subnet for a supported Novatek device.

    Returns a list of dicts: ``[{"ip": "192.168.1.50", "device_id": 271, "model": "<detected model>"}, ...]``,
    sorted by IP. Returns an empty list if nothing is found.
    """
    subnets = await async_get_local_subnets(hass)
    if not subnets:
        return []

    candidates: list[ipaddress.IPv4Address] = []
    for net in subnets:
        candidates.extend(net.hosts())
    if not candidates:
        return []

    sem = asyncio.Semaphore(concurrency)
    found: list[dict[str, Any]] = []
    probe_timeout = aiohttp.ClientTimeout(total=timeout)

    async def probe(ip: ipaddress.IPv4Address) -> None:
        url = f"http://{ip}/api/login?device_info"
        async with sem:
            try:
                async with session.get(url, timeout=probe_timeout) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json(content_type=None)
            except (ClientError, asyncio.TimeoutError, ValueError):
                return
            except Exception:  # noqa: BLE001 - never let one bad host kill the scan
                return
            if not isinstance(data, dict) or data.get("STATUS") != "OK":
                return
            device_id = data.get("device_id")
            model = DEVICE_MODELS.get(device_id) if isinstance(device_id, int) else None
            if not model:
                return
            found.append({"ip": str(ip), "device_id": device_id, "model": model})

    _LOGGER.debug("Novatek LAN scan: probing %d hosts", len(candidates))
    await asyncio.gather(*(probe(ip) for ip in candidates))
    found.sort(key=lambda x: ipaddress.IPv4Address(x["ip"]))
    _LOGGER.debug("Novatek LAN scan: %d device(s) found", len(found))
    return found
