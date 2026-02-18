"""Data models for Elgato Key Light API."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LightState:
    """State of a single light, matching the Elgato API JSON shape."""

    on: bool = False
    brightness: int = 50
    temperature: int = 200  # 143 (7000K cool) to 344 (2900K warm)

    def to_api(self) -> dict:
        return {
            "on": 1 if self.on else 0,
            "brightness": self.brightness,
            "temperature": self.temperature,
        }

    @classmethod
    def from_api(cls, data: dict) -> LightState:
        return cls(
            on=bool(data.get("on", 0)),
            brightness=data.get("brightness", 50),
            temperature=data.get("temperature", 200),
        )

    @property
    def temperature_kelvin(self) -> int:
        """Convert Elgato temperature value to Kelvin (approximate)."""
        return int(1_000_000 / self.temperature)


@dataclass
class DeviceInfo:
    """Device information from the /elgato/accessory-info endpoint."""

    product_name: str = ""
    hardware_board_type: int = 0
    firmware_build_number: int = 0
    firmware_version: str = ""
    serial_number: str = ""
    display_name: str = ""

    @classmethod
    def from_api(cls, data: dict) -> DeviceInfo:
        return cls(
            product_name=data.get("productName", ""),
            hardware_board_type=data.get("hardwareBoardType", 0),
            firmware_build_number=data.get("firmwareBuildNumber", 0),
            firmware_version=data.get("firmwareVersion", ""),
            serial_number=data.get("serialNumber", ""),
            display_name=data.get("displayName", ""),
        )


@dataclass
class LightConfig:
    """Configuration for a single light."""

    name: str
    host: str
    port: int = 9123
    id: str = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class PresetValues:
    """Brightness + temperature pair for a preset."""

    brightness: int
    temperature: int


@dataclass
class Preset:
    """A named preset for light settings, with optional per-light overrides."""

    brightness: int
    temperature: int
    per_light: dict[str, PresetValues] = field(default_factory=dict)

    def to_state(
        self,
        light_name: str | None = None,
        device_id: str | None = None,
        on: bool = True,
    ) -> LightState:
        # Check per-light overrides by device ID first, then by name
        for key in (device_id, light_name):
            if key and key in self.per_light:
                vals = self.per_light[key]
                return LightState(on=on, brightness=vals.brightness, temperature=vals.temperature)
        return LightState(on=on, brightness=self.brightness, temperature=self.temperature)


@dataclass
class AppConfig:
    """Top-level application configuration."""

    lights: list[LightConfig] = field(default_factory=list)
    presets: dict[str, Preset] = field(default_factory=dict)
