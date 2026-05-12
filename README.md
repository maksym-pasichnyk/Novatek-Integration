# Novatek

Effortlessly connect, discover, and monitor your Novatek-Electro Wi-Fi power meter or voltage relay in Home Assistant with this fully local LAN integration. It talks directly to supported EM-125, EM-125S, EM-126T, EM-126TS, and EM-129 devices over the documented HTTP API, exposes native Home Assistant sensor entities, and keeps everyday polling on your network instead of in a vendor cloud.

## Features

- **Local LAN integration:** Direct HTTP communication with the device, no vendor cloud required for normal operation.
- **Automatic discovery:** Supports DHCP discovery for compatible hostnames and active local subnet scanning from the Add Integration flow.
- **UI-based setup:** Config-flow based, with no YAML required.
- **Broad device support:** Recognizes EM-125, EM-125S, EM-126T, EM-126TS, and EM-129 models.
- **Energy dashboard ready:** Exposes active energy as a `total_increasing` energy sensor suitable for Home Assistant Energy.
- **Rich electrical telemetry:** Track voltage, current, frequency, active power, apparent power, active energy, and apparent energy.
- **Adjustable polling:** Change the polling interval later from the integration options dialog.
- **Flexible installation:** Install through HACS or manually under `custom_components/novatek`.

## Requirements

- Home Assistant `2024.4.0` or newer
- A Novatek-Electro EM-125/EM-126/EM-129 family device reachable from Home Assistant over HTTP
- The device password used for its built-in web/API login
- Network access from Home Assistant to the device on your LAN

## Installation

### Via HACS (recommended)

1. Open HACS -> Integrations -> menu -> **Custom repositories**.
2. Add this repository URL with category **Integration**.
3. Install **Novatek**.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/novatek` into your Home Assistant config directory under `custom_components/`.
2. Restart Home Assistant.

## Setup

1. Open **Settings -> Devices & services -> Add Integration**.
2. Add **Novatek**, or wait for DHCP discovery to offer a compatible device automatically.
3. If you add it manually, pick one of the discovered devices found on your local subnet.
4. Enter the device password during setup.
5. Optionally adjust the polling interval later in the integration's **Configure** dialog.

## Authentication

The device uses a local SHA-1 challenge-response login flow.

- The integration first reads the model identifier and a per-session salt from the device.
- It then computes `SHA1(<model_name> + <password> + <salt>)` and exchanges that for a session ID.
- All subsequent reads are performed locally against the authenticated session.

After setup, day-to-day polling stays local over your LAN.

## Entities

- **Sensors:** Voltage, Current, Frequency, Active power, Apparent power, Active energy, Apparent energy
- **Disabled by default:** Apparent energy

## Services

This integration does not currently expose custom Home Assistant services.

## Caveats

- The device only allows one active web/API session at a time. Opening the device's own web UI will invalidate Home Assistant's session, and vice versa. The integration re-authenticates on the next poll, but entities may briefly show as unavailable.
- DHCP discovery matches hostnames advertising as `em-129*`, `em-126*`, `em-125*`, and `novatek*`.
- Some firmwares may lose their default gateway after DHCP lease renewal, which can make the device unreachable from other subnets. Keeping Home Assistant on the same LAN or using a stable network configuration is safer.
- The polling interval can be configured between `5` and `3600` seconds. The default is `5` seconds.

## Supported Devices

- **EM-125**
- **EM-125S**
- **EM-126T**
- **EM-126TS**
- **EM-129**
