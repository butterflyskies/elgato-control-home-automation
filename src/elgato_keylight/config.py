"""Configuration loader with hardcoded defaults."""

from __future__ import annotations

import tomllib
from pathlib import Path

from elgato_keylight.models import AppConfig, LightConfig, Preset, PresetValues

CONFIG_PATH = Path.home() / ".config" / "elgato-keylight" / "config.toml"

# Hardcoded defaults so it works out of the box
DEFAULT_LIGHTS = [
    LightConfig(name="right", host="192.168.0.60"),
    LightConfig(name="left", host="192.168.0.62"),
]

DEFAULT_PRESETS = {
    "bright": Preset(brightness=100, temperature=200),
    "dim": Preset(brightness=15, temperature=250),
    "warm": Preset(brightness=60, temperature=320),
    "cool": Preset(brightness=70, temperature=155),
    "video": Preset(brightness=55, temperature=215),
    "webcam": Preset(
        brightness=32,
        temperature=179,
        per_light={
            "right": PresetValues(brightness=18, temperature=181),
            "left": PresetValues(brightness=46, temperature=177),
        },
    ),
}


def load_config() -> AppConfig:
    """Load config from TOML file, falling back to hardcoded defaults."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        return _parse_config(data)
    return AppConfig(lights=list(DEFAULT_LIGHTS), presets=dict(DEFAULT_PRESETS))


def _parse_config(data: dict) -> AppConfig:
    lights = []
    for light_data in data.get("lights", []):
        lights.append(
            LightConfig(
                name=light_data["name"],
                host=light_data["host"],
                port=light_data.get("port", 9123),
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

    return AppConfig(
        lights=lights if lights else list(DEFAULT_LIGHTS),
        presets=presets,
    )


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
