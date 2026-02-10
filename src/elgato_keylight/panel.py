"""GTK4 control panel for Elgato Key Lights — per-light brightness and temperature sliders."""

from __future__ import annotations

import json
import urllib.request
from functools import partial
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402


# --- Elgato HTTP helpers (stdlib only, no httpx) ---


def _api_get(host: str, port: int, path: str) -> dict:
    url = f"http://{host}:{port}{path}"
    with urllib.request.urlopen(url, timeout=3) as resp:
        return json.loads(resp.read())


def _api_put(host: str, port: int, path: str, data: dict) -> dict:
    url = f"http://{host}:{port}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read())


def _get_light_state(host: str, port: int) -> dict:
    data = _api_get(host, port, "/elgato/lights")
    return data["lights"][0]


def _set_light_state(host: str, port: int, on: int, brightness: int, temperature: int) -> None:
    payload = {"numberOfLights": 1, "lights": [{"on": on, "brightness": brightness, "temperature": temperature}]}
    _api_put(host, port, "/elgato/lights", payload)


# --- Config loading (duplicated minimally to avoid import chain) ---


def _load_lights() -> list[dict]:
    """Load light configs — tries TOML config, falls back to hardcoded defaults."""
    import tomllib
    from pathlib import Path

    config_path = Path.home() / ".config" / "elgato-keylight" / "config.toml"
    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        lights = data.get("lights", [])
        if lights:
            return [{"name": l["name"], "host": l["host"], "port": l.get("port", 9123)} for l in lights]

    return [
        {"name": "right", "host": "192.168.0.60", "port": 9123},
        {"name": "left", "host": "192.168.0.62", "port": 9123},
    ]


def _load_presets() -> dict[str, dict]:
    """Load presets from config."""
    import tomllib
    from pathlib import Path

    config_path = Path.home() / ".config" / "elgato-keylight" / "config.toml"
    defaults = {
        "webcam": {"brightness": 32, "temperature": 179,
                    "right": {"brightness": 18, "temperature": 181},
                    "left": {"brightness": 46, "temperature": 177}},
        "bright": {"brightness": 100, "temperature": 200},
        "dim": {"brightness": 15, "temperature": 250},
        "warm": {"brightness": 60, "temperature": 320},
        "cool": {"brightness": 70, "temperature": 155},
        "video": {"brightness": 55, "temperature": 215},
    }
    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        presets = data.get("presets", {})
        if presets:
            merged = dict(defaults)
            merged.update(presets)
            return merged
    return defaults


def _temp_to_kelvin(temp: int) -> int:
    return int(1_000_000 / temp) if temp > 0 else 0


# --- GTK4 Panel ---


class LightControl:
    """Slider controls for a single light."""

    def __init__(self, name: str, host: str, port: int):
        self.name = name
        self.host = host
        self.port = port
        self._debounce_id: int | None = None
        self._updating_from_api = False

        # Fetch initial state
        try:
            state = _get_light_state(host, port)
            self.current_on = state.get("on", 0)
            self.current_brightness = state.get("brightness", 50)
            self.current_temperature = state.get("temperature", 200)
        except Exception:
            self.current_on = 0
            self.current_brightness = 50
            self.current_temperature = 200

        # Build UI
        self.frame = Gtk.Frame()
        self.frame.add_css_class("light-frame")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        self.frame.set_child(box)

        # Header with name and on/off toggle
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label=name.capitalize())
        label.add_css_class("light-name")
        label.set_hexpand(True)
        label.set_halign(Gtk.Align.START)
        header.append(label)

        self.power_switch = Gtk.Switch()
        self.power_switch.set_active(bool(self.current_on))
        self.power_switch.connect("state-set", self._on_power_toggle)
        header.append(self.power_switch)
        box.append(header)

        # Brightness slider
        bright_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bright_label = Gtk.Label(label="Brightness")
        bright_label.set_size_request(90, -1)
        bright_label.set_halign(Gtk.Align.START)
        bright_box.append(bright_label)

        self.brightness_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 3, 100, 1)
        self.brightness_scale.set_value(self.current_brightness)
        self.brightness_scale.set_hexpand(True)
        self.brightness_scale.connect("value-changed", self._on_slider_changed)
        bright_box.append(self.brightness_scale)

        self.brightness_value = Gtk.Label(label=f"{self.current_brightness}%")
        self.brightness_value.set_size_request(45, -1)
        bright_box.append(self.brightness_value)
        box.append(bright_box)

        # Temperature slider (143=cool to 344=warm)
        temp_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        temp_label = Gtk.Label(label="Temperature")
        temp_label.set_size_request(90, -1)
        temp_label.set_halign(Gtk.Align.START)
        temp_box.append(temp_label)

        self.temp_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 143, 344, 1)
        self.temp_scale.set_value(self.current_temperature)
        self.temp_scale.set_hexpand(True)
        self.temp_scale.set_inverted(True)  # left=cool(high K), right=warm(low K)
        self.temp_scale.connect("value-changed", self._on_slider_changed)
        temp_box.append(self.temp_scale)

        kelvin = _temp_to_kelvin(self.current_temperature)
        self.temp_value = Gtk.Label(label=f"{kelvin}K")
        self.temp_value.set_size_request(55, -1)
        temp_box.append(self.temp_value)
        box.append(temp_box)

    def _on_power_toggle(self, switch: Gtk.Switch, state: bool) -> bool:
        self.current_on = 1 if state else 0
        self._schedule_update()
        return False

    def _on_slider_changed(self, scale: Gtk.Scale) -> None:
        if self._updating_from_api:
            return
        brightness = int(self.brightness_scale.get_value())
        temperature = int(self.temp_scale.get_value())
        self.brightness_value.set_label(f"{brightness}%")
        self.temp_value.set_label(f"{_temp_to_kelvin(temperature)}K")
        self.current_brightness = brightness
        self.current_temperature = temperature
        # Turn on if adjusting while off
        if not self.current_on:
            self.current_on = 1
            self._updating_from_api = True
            self.power_switch.set_active(True)
            self._updating_from_api = False
        self._schedule_update()

    def _schedule_update(self) -> None:
        """Debounce — send update 150ms after last change."""
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(150, self._send_update)

    def _send_update(self) -> bool:
        self._debounce_id = None
        try:
            _set_light_state(self.host, self.port, self.current_on, self.current_brightness, self.current_temperature)
        except Exception:
            pass  # don't crash the UI on network hiccup
        return False  # don't repeat

    def set_values(self, brightness: int, temperature: int, on: bool = True) -> None:
        """Set slider values programmatically (for presets)."""
        self._updating_from_api = True
        self.current_on = 1 if on else 0
        self.current_brightness = brightness
        self.current_temperature = temperature
        self.power_switch.set_active(on)
        self.brightness_scale.set_value(brightness)
        self.temp_scale.set_value(temperature)
        self.brightness_value.set_label(f"{brightness}%")
        self.temp_value.set_label(f"{_temp_to_kelvin(temperature)}K")
        self._updating_from_api = False
        self._schedule_update()


class ControlPanel(Adw.Application):
    def __init__(self):
        super().__init__(application_id="dev.butterflysky.elgato-panel")
        self.connect("activate", self._on_activate)

    def _on_activate(self, app: Adw.Application) -> None:
        # Check for existing window
        win = app.get_active_window()
        if win:
            win.present()
            return

        win = Adw.ApplicationWindow(application=app)
        win.set_title("Key Lights")
        win.set_default_size(380, -1)
        win.set_resizable(False)

        # Main layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        win.set_content(main_box)

        # Light controls
        lights = _load_lights()
        self.controls: dict[str, LightControl] = {}
        for light in lights:
            ctrl = LightControl(light["name"], light["host"], light["port"])
            self.controls[light["name"]] = ctrl
            main_box.append(ctrl.frame)

        # Preset buttons
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        preset_box.set_halign(Gtk.Align.CENTER)
        preset_box.set_margin_top(4)

        presets = _load_presets()
        button_order = ["webcam", "video", "bright", "dim", "warm", "cool"]
        for name in button_order:
            if name not in presets:
                continue
            btn = Gtk.Button(label=name.capitalize())
            btn.add_css_class("preset-btn")
            btn.connect("clicked", partial(self._on_preset, name=name, preset=presets[name]))
            preset_box.append(btn)

        # All off button
        off_btn = Gtk.Button(label="Off")
        off_btn.add_css_class("destructive-action")
        off_btn.connect("clicked", self._on_all_off)
        preset_box.append(off_btn)

        main_box.append(preset_box)

        # Apply CSS
        css = Gtk.CssProvider()
        css.load_from_string(
            """
            .light-name { font-weight: bold; font-size: 14px; }
            .light-frame { margin-bottom: 4px; }
            .preset-btn { min-width: 50px; }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        win.present()

    def _on_preset(self, btn: Gtk.Button, name: str, preset: dict) -> None:
        for light_name, ctrl in self.controls.items():
            # Check for per-light override
            if light_name in preset and isinstance(preset[light_name], dict):
                override = preset[light_name]
                ctrl.set_values(override["brightness"], override["temperature"])
            else:
                ctrl.set_values(preset.get("brightness", 50), preset.get("temperature", 200))

    def _on_all_off(self, btn: Gtk.Button) -> None:
        for ctrl in self.controls.values():
            ctrl.set_values(ctrl.current_brightness, ctrl.current_temperature, on=False)


def main():
    app = ControlPanel()
    app.run(None)


if __name__ == "__main__":
    main()
