"""Configuration loader with mDNS discovery fallback."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from elgato_keylight.models import AppConfig, LightConfig, Preset, PresetValues

CONFIG_PATH = Path.home() / ".config" / "elgato-keylight" / "config.toml"

DEFAULT_PRESETS = {
    "bright": Preset(brightness=100, temperature=200),
    "dim": Preset(brightness=15, temperature=250),
    "warm": Preset(brightness=60, temperature=320),
    "cool": Preset(brightness=70, temperature=155),
    "video": Preset(brightness=55, temperature=215),
}


def load_config() -> AppConfig:
    """Load config from TOML file, discovering lights via mDNS when needed."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        return _parse_config(data)

    # No config file — discover lights and use default presets
    lights = _discover_fallback()
    return AppConfig(lights=lights, presets=dict(DEFAULT_PRESETS))


def _discover_fallback() -> list[LightConfig]:
    """Try mDNS discovery, printing an error if nothing is found."""
    from elgato_keylight.discovery import discover_lights

    lights = discover_lights()
    if not lights:
        print(
            "elgato-keylight: no lights found — configure them in "
            "~/.config/elgato-keylight/config.toml or ensure they are "
            "on the local network",
            file=sys.stderr,
        )
    return lights


def _parse_config(data: dict) -> AppConfig:
    lights = []
    for light_data in data.get("lights", []):
        lights.append(
            LightConfig(
                name=light_data["name"],
                host=light_data["host"],
                port=light_data.get("port", 9123),
                id=light_data.get("id", ""),
            )
        )

    presets = dict(DEFAULT_PRESETS)  # start with defaults
    for name, preset_data in data.get("presets", {}).items():
        # Separate per-light overrides (dicts) from global values (ints)
        per_light = {}
        global_brightness = preset_data.get("brightness", 50)
        global_temperature = preset_data.get("temperature", 200)
        for key, val in preset_data.items():
            if isinstance(val, dict):
                per_light[key] = PresetValues(
                    brightness=val["brightness"],
                    temperature=val["temperature"],
                )
        presets[name] = Preset(
            brightness=global_brightness,
            temperature=global_temperature,
            per_light=per_light,
        )

    if not lights:
        lights = _discover_fallback()

    return AppConfig(lights=lights, presets=presets)


def get_lights(names: list[str] | None = None) -> list[LightConfig]:
    """Get light configs, optionally filtered by name."""
    config = load_config()
    if not names:
        return config.lights
    return [l for l in config.lights if l.name in names]


def get_preset(name: str) -> Preset | None:
    """Get a named preset."""
    config = load_config()
    return config.presets.get(name)


def list_presets() -> dict[str, Preset]:
    """List all available presets."""
    return load_config().presets
