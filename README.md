# HDHomeRun XMLTV Proxy

A lightweight XMLTV proxy for Jellyfin and HDHomeRun tuners.

The proxy automatically retrieves the current DeviceAuth value from your HDHomeRun tuner and downloads the official SiliconDust XMLTV guide feed. Jellyfin connects to a stable local URL while the proxy handles DeviceAuth rotation automatically.

## Features

- Automatic HDHomeRun discovery
- Manual tuner configuration for VLANs and routed networks
- Dynamic DeviceAuth retrieval
- XMLTV caching
- Jellyfin-compatible XMLTV endpoint
- Simple web-based setup page
- No SiliconDust credentials stored
- TrueNAS-friendly container deployment

## Requirements

- HDHomeRun tuner
- Jellyfin
- Docker-compatible environment (TrueNAS SCALE, Docker, Portainer, etc.)

## Endpoints

### XMLTV Guide

```text
GET /xmltv
```

Example:

```text
http://SERVER:8080/xmltv
```

### Health Check

```text
GET /healthz
```

Example:

```text
http://SERVER:8080/healthz
```

### Status

```text
GET /status
```

Example:

```text
http://SERVER:8080/status
```

### Manual Refresh

```text
POST /refresh
```

Forces a guide refresh from SiliconDust.

## First Run

When the application starts for the first time:

1. Attempts to discover an HDHomeRun tuner automatically
2. Displays discovered tuner information
3. Allows manual IP entry if discovery fails
4. Saves configuration locally
5. Begins serving XMLTV data

Example manual entry:

```text
192.168.1.50
```

or

```text
http://192.168.1.50/discover.json
```

## Environment Variables

| Variable | Default | Description |
|----------|----------|-------------|
| CONFIG_DIRECTORY | /config | Configuration storage location |
| CACHE_SECONDS | 21600 | XMLTV cache lifetime |
| PORT | 8080 | Application listening port |
| LOG_LEVEL | INFO | Logging level |
| AUTO_DISCOVERY_URL | http://hdhomerun.local/discover.json | Auto-discovery URL |

## Jellyfin Configuration

Add an XMLTV Guide Provider in Jellyfin:

```text
http://YOUR-SERVER-IP:8080/xmltv
```

Then run:

- Refresh Guide Data
- Refresh Tuner Channels

## TrueNAS Example

Container Port:

```text
8080
```

Host Port:

```text
30090
```

Example Jellyfin URL:

```text
http://TRUENAS-IP:30090/xmltv
```

## Project Goals

This project exists because:

- HDHomeRun DeviceAuth values rotate periodically
- Jellyfin expects a stable XMLTV URL
- Existing helper projects may not expose the full SiliconDust guide feed consistently

This proxy keeps the setup simple while exposing the official SiliconDust XMLTV data directly.

## License

This project is licensed under the MIT License. See the LICENSE
file for details.

## Development Process

Portions of this project were produced with the assistance of generative AI tools. The project owner reviewed, modified, tested, and integrated all code contained in this repository and is responsible for the final released work.

## Third-Party Components

This project uses:

- Flask (BSD-3-Clause)
- Requests (Apache-2.0)
- Gunicorn (MIT)

See each project's repository for full license details.

## Disclaimer

This project is an independent open source utility and is not affiliated with,
endorsed by, or sponsored by SiliconDust, HDHomeRun, Jellyfin, TrueNAS,
iXsystems, or any related organization.

HDHomeRun is a trademark of SiliconDust USA, Inc.
Jellyfin is a trademark of the Jellyfin Project.
TrueNAS is a trademark of iXsystems, Inc.