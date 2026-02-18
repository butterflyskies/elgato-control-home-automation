"""mDNS discovery of Elgato Key Lights via avahi-browse."""

from __future__ import annotations

import subprocess
import sys

from elgato_keylight.models import LightConfig


def discover_lights() -> list[LightConfig]:
    """Discover Elgato lights on the local network via mDNS.

    Uses avahi-browse to find ``_elg._tcp`` services.  Returns an empty
    list (with a warning on stderr) when avahi-browse is unavailable or
    no lights respond within the timeout.
    """
    try:
        out = subprocess.check_output(
            ["avahi-browse", "-rpt", "_elg._tcp"],
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).decode()
    except FileNotFoundError:
        print(
            "elgato-keylight: avahi-browse not found — install avahi-tools "
            "or configure lights in ~/.config/elgato-keylight/config.toml",
            file=sys.stderr,
        )
        return []
    except Exception:
        return []

    lights: list[LightConfig] = []
    seen: set[str] = set()
    for line in out.splitlines():
        # Resolved IPv4 lines: =;iface;IPv4;name;_elg._tcp;domain;hostname;ip;port;txt
        if not line.startswith("=") or ";IPv4;" not in line:
            continue
        parts = line.split(";")
        if len(parts) < 9:
            continue
        raw_name = parts[3].replace("\\032", " ")
        host = parts[7]
        port = int(parts[8])
        if host in seen:
            continue
        seen.add(host)

        # Extract short name: "Elgato Key Light - right" -> "right"
        name = raw_name
        if " - " in raw_name:
            name = raw_name.split(" - ", 1)[1].strip()

        # Extract device ID from TXT record: "id=AA:BB:CC:DD:EE:FF"
        device_id = ""
        txt = ";".join(parts[9:]) if len(parts) > 9 else ""
        for token in txt.replace('"', " ").split():
            if token.startswith("id="):
                device_id = token[3:]
                break

        lights.append(
            LightConfig(name=name.lower(), host=host, port=port, id=device_id)
        )

    lights.sort(key=lambda lc: lc.name)
    return lights
