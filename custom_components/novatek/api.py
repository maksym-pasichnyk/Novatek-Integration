"""HTTP client for the Novatek EM-125 / 126 / 129 family.

Protocol details extracted from Novatek-Electro's documented WebAPI and
verified against vedga/novatek (GPL-3.0):

    Authentication is a challenge–response:

        GET /api/login?device_info
            -> {"STATUS": "OK", "device_id": <int>}      # identifies model

        GET /api/login?salt
            -> {"STATUS": "OK", "SALT": "<hex>"}         # per-session salt

        hash = SHA1(<model_name> + <password> + <salt>)  # UTF-8
        GET /api/login?login=<hash_hex>
            -> {"STATUS": "OK", "SID": "<session_id>"}

    All subsequent requests are made against ``/<SID>/api/...``. Only one
    web/API session is allowed at a time — opening the device's web UI
    will invalidate the SID and vice versa.

Live readings come from ``/<SID>/api/all/get?<key>`` and return scaled
integers; the scaling is fixed per key:

    volt_msr   -> volts  (raw / 10)
    cur_msr    -> amps   (raw / 100)
    freq_msr   -> hertz  (raw / 100)
    powa_msr   -> watts  (raw)
    pows_msr   -> VA     (raw)
    enrga_msr  -> Wh     (raw, monotonically increasing)
    enrgs_msr  -> VAh    (raw, monotonically increasing)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientTimeout

from .const import (
    DEFAULT_TIMEOUT,
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
)

_LOGGER = logging.getLogger(__name__)

# device_id (from /api/login?device_info) -> model name string.
# The model name is part of the SHA-1 input, so it must match exactly.
DEVICE_MODELS: dict[int, str] = {
    243: "EM-125",
    293: "EM-126T",
    255: "EM-125S",
    285: "EM-126TS",
    271: "EM-129",
}

# Measurement keys requested via /api/all/get?<key>. Tuple of:
#   (api_key, canonical_key, scale_divisor)
_MEASUREMENTS: tuple[tuple[str, str, float], ...] = (
    ("volt_msr", KEY_VOLTAGE, 10.0),
    ("cur_msr", KEY_CURRENT, 100.0),
    ("freq_msr", KEY_FREQUENCY, 100.0),
    ("powa_msr", KEY_ACTIVE_POWER, 1.0),
    ("pows_msr", KEY_APPARENT_POWER, 1.0),
    ("enrga_msr", KEY_ENERGY_TOTAL, 1.0),
    ("enrgs_msr", KEY_APPARENT_ENERGY, 1.0),
)


class NovatekError(Exception):
    """Base error for the Novatek client."""


class NovatekConnectionError(NovatekError):
    """Raised when the device is unreachable or replies with a non-success status."""


class NovatekAuthError(NovatekError):
    """Raised when authentication fails (bad password or unknown model)."""


class NovatekClient:
    """Async client for Novatek-Electro EM-125/126/129 power meters."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        password: str,
        *,
        port: int = 80,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._password = password
        self._timeout = ClientTimeout(total=timeout)
        # Auth state, populated by _authenticate():
        self._sid: str | None = None
        self._device_id: int | None = None
        self._model: str | None = None

    # ----------------------------------------------------------------- public

    @property
    def host(self) -> str:
        return self._host

    @property
    def model(self) -> str | None:
        return self._model

    async def async_test_connection(self) -> dict[str, Any]:
        """Authenticate and pull one set of readings; used by config flow."""
        return await self.async_get_data()

    async def async_get_data(self) -> dict[str, Any]:
        """Authenticate if needed, then poll every supported reading.

        On a stale/invalidated session we re-authenticate once and retry.
        Raises ``NovatekAuthError`` for password problems,
        ``NovatekConnectionError`` otherwise.
        """
        try:
            return await self._collect()
        except NovatekAuthError:
            # Don't retry on auth errors — the password is wrong.
            raise
        except NovatekConnectionError:
            # Session may have been invalidated (someone opened the web UI,
            # device rebooted, etc.). Try one full re-auth.
            self._sid = None
            return await self._collect()

    # ----------------------------------------------------------------- private

    def _base_url(self) -> str:
        if self._port in (80, 0):
            return f"http://{self._host}"
        return f"http://{self._host}:{self._port}"

    async def _collect(self) -> dict[str, Any]:
        if not self._sid:
            await self._authenticate()

        out: dict[str, Any] = {}
        if self._model:
            out[KEY_MODEL] = self._model
            # Use model+host as a stable identity until the device exposes a serial.
            out[KEY_SERIAL] = f"{self._model}-{self._host}"

        for api_key, canonical_key, divisor in _MEASUREMENTS:
            value = await self._get_measurement(api_key)
            if value is None:
                continue
            out[canonical_key] = value / divisor if divisor != 1.0 else float(value)
        return out

    async def _authenticate(self) -> None:
        """Run the full SHA-1 challenge handshake and remember the SID."""
        info = await self._raw_get("/api/login?device_info")
        device_id = info.get("device_id")
        if not isinstance(device_id, int):
            raise NovatekConnectionError(
                f"Unexpected device_info payload: {info!r}"
            )
        model = DEVICE_MODELS.get(device_id)
        if not model:
            raise NovatekAuthError(
                f"Unsupported device_id {device_id}; not an EM-125/126/129."
            )

        salt_resp = await self._raw_get("/api/login?salt")
        salt = salt_resp.get("SALT")
        if not isinstance(salt, str) or not salt:
            raise NovatekConnectionError(f"Unexpected salt payload: {salt_resp!r}")

        digest = hashlib.sha1(
            f"{model}{self._password}{salt}".encode("utf-8")
        ).hexdigest()

        login = await self._raw_get(f"/api/login?login={digest}")
        sid = login.get("SID")
        if not isinstance(sid, str) or not sid:
            # Device returns STATUS!=OK on bad password — _raw_get would have
            # already raised, but be defensive.
            raise NovatekAuthError("Authentication failed (bad password?).")

        self._device_id = device_id
        self._model = model
        self._sid = sid
        _LOGGER.debug(
            "Novatek authenticated host=%s model=%s sid=%s", self._host, model, sid
        )

    async def _get_measurement(self, key: str) -> int | None:
        """Fetch one measurement key. Returns ``None`` if it isn't supported."""
        assert self._sid, "must authenticate first"
        payload = await self._raw_get(f"/{self._sid}/api/all/get?{key}")
        value = payload.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            _LOGGER.debug("Non-integer reading for %s: %r", key, value)
            return None

    async def _raw_get(self, path: str) -> dict[str, Any]:
        """GET <base>/<path>, parse JSON, enforce STATUS==OK."""
        url = f"{self._base_url()}{path}"
        try:
            async with self._session.get(url, timeout=self._timeout) as resp:
                if resp.status in (401, 403):
                    raise NovatekAuthError(f"HTTP {resp.status} from {url}")
                if resp.status >= 400:
                    raise NovatekConnectionError(f"HTTP {resp.status} from {url}")
                data = await resp.json(content_type=None)
        except ClientResponseError as err:
            raise NovatekConnectionError(str(err)) from err
        except (ClientError, asyncio.TimeoutError) as err:
            raise NovatekConnectionError(str(err)) from err
        except ValueError as err:
            # Non-JSON body — most likely an invalidated SID returning HTML.
            raise NovatekConnectionError(f"Non-JSON response from {url}: {err}") from err

        if not isinstance(data, dict):
            raise NovatekConnectionError(f"Unexpected payload from {url}: {data!r}")
        if data.get("STATUS") != "OK":
            # Auth failures and stale SIDs both surface as non-OK STATUS.
            # The coordinator/test_connection layer decides whether to retry.
            if "login" in path:
                raise NovatekAuthError(f"Login refused by device: {data!r}")
            raise NovatekConnectionError(f"STATUS={data.get('STATUS')!r} from {url}")
        return data
