import json
import logging
import os
import time
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import requests
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template_string,
    request,
    url_for,
)

app = Flask(__name__)

# TrueNAS should set CONFIG_DIRECTORY=/config and mount persistent
# storage there. The local default keeps Windows testing simple.
CONFIG_DIRECTORY = Path(
    os.getenv("CONFIG_DIRECTORY", "./config")
)
CONFIG_FILE = CONFIG_DIRECTORY / "settings.json"

SILICONDUST_XMLTV_URL = os.getenv(
    "SILICONDUST_XMLTV_URL",
    "https://api.hdhomerun.com/api/xmltv",
)

AUTO_DISCOVERY_URL = os.getenv(
    "AUTO_DISCOVERY_URL",
    "http://hdhomerun.local/discover.json",
)

CACHE_SECONDS = int(
    os.getenv("CACHE_SECONDS", "21600")
)

REQUEST_TIMEOUT_SECONDS = int(
    os.getenv("REQUEST_TIMEOUT_SECONDS", "180")
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger("hdhomerun-xmltv-proxy")

cache_lock = Lock()

cached_xml = None
cached_at = 0.0
cached_channel_count = 0
cached_program_count = 0
cached_xml_size = 0


class GuideError(Exception):
    """Raised when tuner or guide communication fails."""


class ConfigurationError(Exception):
    """Raised when the application configuration is unavailable."""


BASE_STYLE = """
<style>
    :root {
        color-scheme: dark;
        font-family: Inter, Arial, sans-serif;
        background: #111827;
        color: #f9fafb;
    }

    * {
        box-sizing: border-box;
    }

    body {
        margin: 0;
        min-height: 100vh;
        background:
            radial-gradient(
                circle at top left,
                #1f3b5e,
                transparent 42%
            ),
            #111827;
    }

    .page {
        max-width: 850px;
        margin: 0 auto;
        padding: 40px 20px;
    }

    .card {
        margin-bottom: 20px;
        padding: 28px;
        border: 1px solid #374151;
        border-radius: 14px;
        background: rgba(31, 41, 55, 0.96);
        box-shadow: 0 20px 45px rgba(0, 0, 0, 0.28);
    }

    h1 {
        margin-top: 0;
        font-size: 30px;
    }

    h2 {
        margin-top: 0;
        font-size: 21px;
    }

    p {
        color: #d1d5db;
        line-height: 1.55;
    }

    label {
        display: block;
        margin-bottom: 8px;
        font-weight: 600;
    }

    input {
        width: 100%;
        margin-bottom: 15px;
        padding: 13px;
        border: 1px solid #4b5563;
        border-radius: 8px;
        background: #111827;
        color: #ffffff;
        font-size: 15px;
    }

    button,
    .button {
        display: inline-block;
        margin-right: 8px;
        margin-bottom: 8px;
        padding: 12px 18px;
        border: 0;
        border-radius: 8px;
        background: #2563eb;
        color: #ffffff;
        font-weight: 600;
        text-decoration: none;
        cursor: pointer;
    }

    button.secondary,
    .button.secondary {
        background: #4b5563;
    }

    button:hover,
    .button:hover {
        filter: brightness(1.12);
    }

    .success,
    .error,
    .warning {
        margin-bottom: 18px;
        padding: 14px;
        border-radius: 8px;
    }

    .success {
        border: 1px solid #059669;
        background: #064e3b;
        color: #d1fae5;
    }

    .error {
        border: 1px solid #dc2626;
        background: #7f1d1d;
        color: #fee2e2;
    }

    .warning {
        border: 1px solid #d97706;
        background: #78350f;
        color: #fef3c7;
    }

    .device {
        margin: 16px 0;
        padding: 18px;
        border: 1px solid #374151;
        border-radius: 10px;
        background: #111827;
    }

    .device p {
        margin: 8px 0;
    }

    .device strong {
        color: #93c5fd;
    }

    .grid {
        display: grid;
        grid-template-columns:
            repeat(auto-fit, minmax(150px, 1fr));
        gap: 14px;
        margin: 18px 0;
    }

    .metric {
        padding: 16px;
        border: 1px solid #374151;
        border-radius: 10px;
        background: #111827;
    }

    .metric .value {
        display: block;
        margin-top: 6px;
        color: #93c5fd;
        font-size: 24px;
        font-weight: 700;
    }

    code {
        padding: 3px 6px;
        border-radius: 5px;
        background: #111827;
        color: #bfdbfe;
        overflow-wrap: anywhere;
    }

    .footer {
        margin-top: 20px;
        color: #9ca3af;
        font-size: 13px;
        text-align: center;
    }
</style>
"""


SETUP_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <title>HDHomeRun XMLTV Proxy Setup</title>

    {{ style|safe }}
</head>

<body>
<div class="page">

    <div class="card">
        <h1>HDHomeRun XMLTV Proxy</h1>

        <p>
            Configure the HDHomeRun tuner that this proxy will use.
            The proxy retrieves a fresh DeviceAuth value whenever it
            refreshes the official SiliconDust XMLTV feed.
        </p>

        {% if message %}
        <div class="{{ message_type }}">
            {{ message }}
        </div>
        {% endif %}

        {% if device %}

        <div class="success">
            An HDHomeRun tuner was discovered automatically.
        </div>

        <div class="device">
            <p>
                <strong>Name:</strong>
                {{ device.get("FriendlyName", "Unknown") }}
            </p>

            <p>
                <strong>Model:</strong>
                {{ device.get("ModelNumber", "Unknown") }}
            </p>

            <p>
                <strong>Device ID:</strong>
                {{ device.get("DeviceID", "Unknown") }}
            </p>

            <p>
                <strong>Firmware:</strong>
                {{ device.get("FirmwareVersion", "Unknown") }}
            </p>

            <p>
                <strong>Discovery URL:</strong>
                <code>{{ discovered_url }}</code>
            </p>
        </div>

        {{ url_for('save_setup') }}
            <input
                type="hidden"
                name="hdhr_value"
                value="{{ discovered_url }}"
            >

            <button type="submit">
                Use This Tuner
            </button>
        </form>

        {% else %}

        <div class="warning">
            Automatic discovery did not find an HDHomeRun.
            This can occur when the tuner is on another VLAN,
            multicast DNS is unavailable, or container network
            discovery is restricted.
        </div>

         }}"
        >
            <button type="submit">
                Try Automatic Discovery Again
            </button>
        </form>

        {% endif %}
    </div>

    <div class="card">

        <h2>Manual Tuner Configuration</h2>

        <p>
            Enter either the tuner IP address or the full
            <code>discover.json</code> URL.
        </p>

        <p>
            Examples:
            <code>192.168.1.50</code>
            or
            <code>http://192.168.1.50/discover.json</code>
        </p>

         }}"
        >

            <label for="hdhr_value">
                HDHomeRun IP Address or Discovery URL
            </label>

            <input
                id="hdhr_value"
                name="hdhr_value"
                type="text"
                placeholder="192.168.1.50"
                value="{{ current_value or '' }}"
                required
            >

            <button type="submit">
                Validate and Save
            </button>

        </form>

    </div>

    <div class="footer">
        Designed for Jellyfin deployments on TrueNAS and
        other container platforms.
    </div>

</div>
</body>
</html>
"""

DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <title>HDHomeRun XMLTV Proxy</title>

    {{ style|safe }}
</head>

<body>
<div class="page">
    <div class="card">
        <h1>HDHomeRun XMLTV Proxy</h1>

        {% if message %}
            <div class="{{ message_type }}">
                {{ message }}
            </div>
        {% endif %}

        <div class="device">
            <p>
                <strong>Tuner:</strong>
                {{ device.get("FriendlyName", "Unknown") }}
            </p>

            <p>
                <strong>Model:</strong>
                {{ device.get("ModelNumber", "Unknown") }}
            </p>

            <p>
                <strong>Device ID:</strong>
                {{ device.get("DeviceID", "Unknown") }}
            </p>

            <p>
                <strong>Configured URL:</strong>
                <code>{{ hdhr_url }}</code>
            </p>
        </div>

        <div class="grid">
            <div class="metric">
                Channels
                <span class="value">{{ channels }}</span>
            </div>

            <div class="metric">
                Programs
                <span class="value">{{ programs }}</span>
            </div>

            <div class="metric">
                XML Size
                <span class="value">{{ xml_size }}</span>
            </div>

            <div class="metric">
                Cache Age
                <span class="value">{{ cache_age }}</span>
            </div>
        </div>

        <p>
            Jellyfin XMLTV URL:
            <code>{{ xmltv_url }}</code>
        </p>

         }}"
            target="_blank"
            rel="noopener noreferrer"
        >
            Open XMLTV Feed
        </a>

        <button id="refreshButton" type="button">
            Refresh Guide Now
        </button>

         }}"
        >
            Tuner Settings
        </a>

        <div id="refreshResult"></div>
    </div>

    <div class="card">
        <h2>Service Endpoints</h2>

        <p>
            <code>GET /xmltv</code>
            XMLTV guide data
        </p>

        <p>
            <code>GET /healthz</code>
            service health
        </p>

        <p>
            <code>GET /status</code>
            JSON cache status
        </p>

        <p>
            <code>POST /refresh</code>
            force a full refresh
        </p>
    </div>

    <div class="footer">
        The DeviceAuth value is retrieved dynamically and is not
        stored in the configuration file.
    </div>
</div>

<script>
document
    .getElementById("refreshButton")
    .addEventListener("click", async function () {
        const result =
            document.getElementById("refreshResult");

        result.className = "warning";
        result.textContent = "Refreshing guide data...";

        try {
            const response = await fetch(
                "{{ url_for('refresh_guide') }}",
                {
                    method: "POST"
                }
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.error || "Refresh failed"
                );
            }

            result.className = "success";
            result.textContent =
                "Guide refreshed: " +
                data.channels +
                " channels, " +
                data.programs +
                " programs, " +
                data.bytes +
                " bytes.";

            window.setTimeout(function () {
                window.location.reload();
            }, 1000);
        } catch (error) {
            result.className = "error";
            result.textContent = error.message;
        }
    });
</script>
</body>
</html>
"""


def ensure_config_directory():
    try:
        CONFIG_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as exc:
        raise ConfigurationError(
            f"Unable to create configuration directory "
            f"{CONFIG_DIRECTORY}: {exc}"
        ) from exc


def load_settings():
    if not CONFIG_FILE.exists():
        return {}

    try:
        with CONFIG_FILE.open(
                "r",
                encoding="utf-8",
        ) as file:
            settings = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"Unable to read {CONFIG_FILE}: {exc}"
        ) from exc

    if not isinstance(settings, dict):
        raise ConfigurationError(
            "The configuration file does not contain "
            "a JSON object"
        )

    return settings


def save_settings(settings):
    ensure_config_directory()

    temporary_file = CONFIG_FILE.with_suffix(".tmp")

    try:
        with temporary_file.open(
                "w",
                encoding="utf-8",
        ) as file:
            json.dump(
                settings,
                file,
                indent=2,
            )

        temporary_file.replace(CONFIG_FILE)
    except OSError as exc:
        raise ConfigurationError(
            f"Unable to save {CONFIG_FILE}: {exc}"
        ) from exc


def normalize_hdhr_value(value):
    value = value.strip()

    if not value:
        raise ConfigurationError(
            "An HDHomeRun IP address or URL is required"
        )

    if "://" not in value:
        value = f"http://{value}"

    parsed = urlparse(value)

    if parsed.scheme not in ("http", "https"):
        raise ConfigurationError(
            "The HDHomeRun URL must use HTTP or HTTPS"
        )

    if not parsed.hostname:
        raise ConfigurationError(
            "The HDHomeRun URL does not contain "
            "a valid hostname"
        )

    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError as exc:
        raise ConfigurationError(
            "The HDHomeRun URL contains an invalid port"
        ) from exc

    path = parsed.path.rstrip("/")

    if not path:
        path = "/discover.json"
    elif not path.endswith("/discover.json"):
        path = f"{path}/discover.json"

    return (
        f"{parsed.scheme}://"
        f"{parsed.hostname}"
        f"{port}"
        f"{path}"
    )


def request_device(hdhr_url):
    try:
        response = requests.get(
            hdhr_url,
            timeout=10,
        )

        response.raise_for_status()
        device = response.json()
    except requests.RequestException as exc:
        raise GuideError(
            f"Unable to contact the HDHomeRun at "
            f"{hdhr_url}: {exc}"
        ) from exc
    except ValueError as exc:
        raise GuideError(
            "The HDHomeRun discovery endpoint returned "
            "invalid JSON"
        ) from exc

    required_fields = (
        "DeviceID",
        "DeviceAuth",
    )

    missing_fields = [
        field
        for field in required_fields
        if not device.get(field)
    ]

    if missing_fields:
        raise GuideError(
            "The discovery response is missing: "
            + ", ".join(missing_fields)
        )

    return device


def attempt_auto_discovery():
    try:
        device = request_device(AUTO_DISCOVERY_URL)

        return (
            AUTO_DISCOVERY_URL,
            device,
            None,
        )
    except GuideError as exc:
        logger.info(
            "Automatic discovery failed: %s",
            exc,
        )

        return (
            None,
            None,
            str(exc),
        )


def get_configured_hdhr_url():
    settings = load_settings()
    hdhr_url = settings.get("hdhr_url")

    if not hdhr_url:
        raise ConfigurationError(
            "No HDHomeRun tuner has been configured"
        )

    return hdhr_url


def get_device_auth():
    hdhr_url = get_configured_hdhr_url()
    device = request_device(hdhr_url)

    return device["DeviceAuth"], device


def fetch_xmltv():
    device_auth, device = get_device_auth()

    try:
        response = requests.get(
            SILICONDUST_XMLTV_URL,
            params={
                "DeviceAuth": device_auth,
            },
            headers={
                "Accept": "application/xml,text/xml",
                "Accept-Encoding": "gzip",
                "User-Agent":
                    "HDHomeRun-XMLTV-Proxy/1.0",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        response.raise_for_status()
    except requests.RequestException as exc:
        raise GuideError(
            "Unable to download the SiliconDust "
            f"XMLTV feed: {exc}"
        ) from exc

    xml_data = response.content

    if not xml_data:
        raise GuideError(
            "SiliconDust returned an empty XMLTV response"
        )

    stripped_data = xml_data.lstrip()

    if not (
            stripped_data.startswith(b"<?xml")
            or stripped_data.startswith(b"<tv")
    ):
        raise GuideError(
            "SiliconDust returned data that does not "
            "appear to be XMLTV"
        )

    channel_count = xml_data.count(b"<channel ")
    program_count = xml_data.count(b"<programme ")

    if channel_count == 0:
        raise GuideError(
            "The XMLTV response contains no channels"
        )

    if program_count == 0:
        raise GuideError(
            "The XMLTV response contains no programs"
        )

    logger.info(
        "Downloaded guide for device %s: %s bytes, "
        "%s channels, %s programs",
        device.get("DeviceID"),
        len(xml_data),
        channel_count,
        program_count,
    )

    return (
        xml_data,
        channel_count,
        program_count,
    )


def clear_cache():
    global cached_xml
    global cached_at
    global cached_channel_count
    global cached_program_count
    global cached_xml_size

    with cache_lock:
        cached_xml = None
        cached_at = 0.0
        cached_channel_count = 0
        cached_program_count = 0
        cached_xml_size = 0


def get_cached_xmltv(force_refresh=False):
    global cached_xml
    global cached_at
    global cached_channel_count
    global cached_program_count
    global cached_xml_size

    now = time.time()

    if (
            not force_refresh
            and cached_xml is not None
            and now - cached_at < CACHE_SECONDS
    ):
        return (
            cached_xml,
            cached_channel_count,
            cached_program_count,
            cached_xml_size,
            True,
        )

    with cache_lock:
        now = time.time()

        if (
                not force_refresh
                and cached_xml is not None
                and now - cached_at < CACHE_SECONDS
        ):
            return (
                cached_xml,
                cached_channel_count,
                cached_program_count,
                cached_xml_size,
                True,
            )

        try:
            (
                xml_data,
                channel_count,
                program_count,
            ) = fetch_xmltv()
        except GuideError:
            # If an upstream refresh fails but an older guide is
            # available, return the older guide instead of leaving
            # Jellyfin without any guide information.
            if cached_xml is not None and not force_refresh:
                logger.warning(
                    "Guide refresh failed. Serving stale "
                    "cached XMLTV data."
                )

                return (
                    cached_xml,
                    cached_channel_count,
                    cached_program_count,
                    cached_xml_size,
                    True,
                )

            raise

        cached_xml = xml_data
        cached_at = time.time()
        cached_channel_count = channel_count
        cached_program_count = program_count
        cached_xml_size = len(xml_data)

        return (
            cached_xml,
            cached_channel_count,
            cached_program_count,
            cached_xml_size,
            False,
        )


def format_size(byte_count):
    if byte_count <= 0:
        return "Not cached"

    megabytes = byte_count / (1024 * 1024)

    if megabytes >= 1:
        return f"{megabytes:.1f} MB"

    kilobytes = byte_count / 1024

    return f"{kilobytes:.0f} KB"


def format_cache_age():
    if cached_xml is None:
        return "Not cached"

    age = max(
        0,
        int(time.time() - cached_at),
    )

    if age < 60:
        return f"{age}s"

    if age < 3600:
        return f"{age // 60}m"

    return f"{age // 3600}h"


@app.get("/")
def index():
    try:
        hdhr_url = get_configured_hdhr_url()
        device = request_device(hdhr_url)
    except ConfigurationError:
        return redirect(
            url_for("setup")
        )
    except GuideError as exc:
        return render_template_string(
            DASHBOARD_TEMPLATE,
            style=BASE_STYLE,
            device={},
            hdhr_url="Unavailable",
            channels=cached_channel_count,
            programs=cached_program_count,
            xml_size=format_size(cached_xml_size),
            cache_age=format_cache_age(),
            xmltv_url=(
                    request.url_root.rstrip("/")
                    + "/xmltv"
            ),
            message=str(exc),
            message_type="error",
        )

    return render_template_string(
        DASHBOARD_TEMPLATE,
        style=BASE_STYLE,
        device=device,
        hdhr_url=hdhr_url,
        channels=cached_channel_count,
        programs=cached_program_count,
        xml_size=format_size(cached_xml_size),
        cache_age=format_cache_age(),
        xmltv_url=(
                request.url_root.rstrip("/")
                + "/xmltv"
        ),
        message=None,
        message_type=None,
    )


@app.get("/setup")
def setup():
    current_value = ""

    try:
        current_value = load_settings().get(
            "hdhr_url",
            "",
        )
    except ConfigurationError:
        pass

    (
        discovered_url,
        device,
        discovery_error,
    ) = attempt_auto_discovery()

    message = None
    message_type = None

    if discovery_error and current_value:
        message = (
            "Automatic discovery was unavailable. "
            "The existing manual configuration is "
            "shown below."
        )
        message_type = "warning"

    return render_template_string(
        SETUP_TEMPLATE,
        style=BASE_STYLE,
        device=device,
        discovered_url=discovered_url,
        current_value=current_value,
        message=message,
        message_type=message_type,
    )


@app.post("/discover")
def discover():
    (
        discovered_url,
        device,
        discovery_error,
    ) = attempt_auto_discovery()

    if device:
        return render_template_string(
            SETUP_TEMPLATE,
            style=BASE_STYLE,
            device=device,
            discovered_url=discovered_url,
            current_value="",
            message=(
                "HDHomeRun discovery succeeded."
            ),
            message_type="success",
        )

    return render_template_string(
        SETUP_TEMPLATE,
        style=BASE_STYLE,
        device=None,
        discovered_url=None,
        current_value="",
        message=discovery_error,
        message_type="error",
    ), 404


@app.post("/setup")
def save_setup():
    submitted_value = request.form.get(
        "hdhr_value",
        "",
    )

    try:
        hdhr_url = normalize_hdhr_value(
            submitted_value
        )

        device = request_device(hdhr_url)

        save_settings({
            "hdhr_url": hdhr_url,
            "device_id": device.get("DeviceID"),
            "friendly_name":
                device.get("FriendlyName"),
        })

        clear_cache()

        logger.info(
            "Saved HDHomeRun configuration for "
            "device %s",
            device.get("DeviceID"),
        )

        return redirect(
            url_for("index")
        )
    except (
            ConfigurationError,
            GuideError,
    ) as exc:
        return render_template_string(
            SETUP_TEMPLATE,
            style=BASE_STYLE,
            device=None,
            discovered_url=None,
            current_value=submitted_value,
            message=str(exc),
            message_type="error",
        ), 400


@app.get("/xmltv")
def xmltv():
    try:
        (
            xml_data,
            channel_count,
            program_count,
            xml_size,
            cache_hit,
        ) = get_cached_xmltv()
    except ConfigurationError as exc:
        return jsonify({
            "error": str(exc),
            "setup_url": url_for(
                "setup",
                _external=True,
            ),
        }), 503
    except GuideError as exc:
        logger.error("%s", exc)

        return jsonify({
            "error": str(exc),
        }), 502

    return Response(
        xml_data,
        status=200,
        content_type=(
            "application/xml; charset=utf-8"
        ),
        headers={
            "Cache-Control": "no-store",
            "X-XMLTV-Cache": (
                "HIT"
                if cache_hit
                else "MISS"
            ),
            "X-XMLTV-Channels":
                str(channel_count),
            "X-XMLTV-Programs":
                str(program_count),
            "X-XMLTV-Bytes":
                str(xml_size),
        },
    )


@app.post("/refresh")
def refresh_guide():
    try:
        (
            _,
            channel_count,
            program_count,
            xml_size,
            _,
        ) = get_cached_xmltv(
            force_refresh=True
        )
    except (
            ConfigurationError,
            GuideError,
    ) as exc:
        logger.error("%s", exc)

        return jsonify({
            "error": str(exc),
        }), 502

    return jsonify({
        "status": "refreshed",
        "channels": channel_count,
        "programs": program_count,
        "bytes": xml_size,
    })


@app.get("/status")
def status():
    try:
        hdhr_url = get_configured_hdhr_url()
    except ConfigurationError:
        hdhr_url = None

    cache_age_seconds = None

    if cached_xml is not None:
        cache_age_seconds = max(
            0,
            int(time.time() - cached_at),
        )

    return jsonify({
        "configured": hdhr_url is not None,
        "hdhr_url": hdhr_url,
        "cache_populated":
            cached_xml is not None,
        "cache_age_seconds":
            cache_age_seconds,
        "cache_ttl_seconds":
            CACHE_SECONDS,
        "channels":
            cached_channel_count,
        "programs":
            cached_program_count,
        "xml_bytes":
            cached_xml_size,
    })


@app.get("/healthz")
def health():
    try:
        hdhr_url = get_configured_hdhr_url()
        device = request_device(hdhr_url)
    except ConfigurationError as exc:
        return jsonify({
            "status": "setup-required",
            "error": str(exc),
        }), 503
    except GuideError as exc:
        return jsonify({
            "status": "unhealthy",
            "error": str(exc),
        }), 503

    return jsonify({
        "status": "healthy",
        "device": {
            "friendly_name":
                device.get("FriendlyName"),
            "model_number":
                device.get("ModelNumber"),
            "firmware_version":
                device.get("FirmwareVersion"),
            "device_id":
                device.get("DeviceID"),
        },
    })


@app.get("/version")
def version():
    return jsonify({
        "service": "HDHomeRun XMLTV Proxy",
        "version": "1.0.0",
    })


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


if __name__ == "__main__":
    port = int(
        os.getenv("PORT", "8080")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )