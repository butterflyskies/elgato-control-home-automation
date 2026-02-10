"""GTK4 control panel for Elgato Key Lights — drops down from waybar widget.

Uses hyprctl for window positioning and management (no layer shell).
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from functools import partial

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

APP_ID = "dev.butterflysky.elgato-panel"
PANEL_WIDTH = 380
WAYBAR_HEIGHT = 36
PANEL_GAP = 4
SCREEN_EDGE_PAD = 8


# --- hyprctl helpers ---


def _hyprctl_j(cmd: str) -> dict | list:
    """Run hyprctl with -j and return parsed JSON."""
    out = subprocess.check_output(["hyprctl", cmd, "-j"], timeout=1)
    return json.loads(out)


def _hyprctl_dispatch(cmd: str) -> None:
    subprocess.run(["hyprctl", "dispatch", cmd], timeout=1,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _hyprctl_keyword(key: str, value: str) -> None:
    subprocess.run(["hyprctl", "keyword", key, value], timeout=1,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _get_cursor_pos() -> tuple[int, int]:
    """Get cursor (x, y) via hyprctl."""
    try:
        data = _hyprctl_j("cursorpos")
        return data["x"], data["y"]
    except Exception:
        return 960, 0


def _get_focused_monitor() -> dict:
    """Get the focused monitor's geometry."""
    try:
        monitors = _hyprctl_j("monitors")
        for m in monitors:
            if m.get("focused"):
                return m
        return monitors[0]
    except Exception:
        return {"width": 1920, "height": 1080, "x": 0, "y": 0}


def _setup_window_rules() -> None:
    """Set Hyprland window rules for the panel (idempotent)."""
    rules = [
        f"float,class:{APP_ID}",
        f"pin,class:{APP_ID}",
        f"noanim,class:{APP_ID}",
        f"noborder,class:{APP_ID}",
        f"noshadow,class:{APP_ID}",
        f"nofocus,class:{APP_ID},title:backdrop",
        f"noblur,class:{APP_ID},title:backdrop",
    ]
    for rule in rules:
        _hyprctl_keyword("windowrulev2", rule)


def _move_window(title: str, x: int, y: int) -> None:
    """Move a window by title to exact pixel position."""
    _hyprctl_dispatch(f"movewindowpixel exact {x} {y},title:{title}")


def _resize_window(title: str, w: int, h: int) -> None:
    """Resize a window by title."""
    _hyprctl_dispatch(f"resizewindowpixel exact {w} {h},title:{title}")


# --- Elgato HTTP helpers (stdlib only) ---


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


# --- Config loading ---


def _load_lights() -> list[dict]:
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

        try:
            state = _get_light_state(host, port)
            self.current_on = state.get("on", 0)
            self.current_brightness = state.get("brightness", 50)
            self.current_temperature = state.get("temperature", 200)
        except Exception:
            self.current_on = 0
            self.current_brightness = 50
            self.current_temperature = 200

        self.frame = Gtk.Frame()
        self.frame.add_css_class("light-frame")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        self.frame.set_child(box)

        # Header
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

        # Brightness
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

        # Temperature
        temp_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        temp_label = Gtk.Label(label="Temperature")
        temp_label.set_size_request(90, -1)
        temp_label.set_halign(Gtk.Align.START)
        temp_box.append(temp_label)

        self.temp_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 143, 344, 1)
        self.temp_scale.set_value(self.current_temperature)
        self.temp_scale.set_hexpand(True)
        self.temp_scale.set_inverted(True)
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
        if not self.current_on:
            self.current_on = 1
            self._updating_from_api = True
            self.power_switch.set_active(True)
            self._updating_from_api = False
        self._schedule_update()

    def _schedule_update(self) -> None:
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(150, self._send_update)

    def _send_update(self) -> bool:
        self._debounce_id = None
        try:
            _set_light_state(self.host, self.port, self.current_on, self.current_brightness, self.current_temperature)
        except Exception:
            pass
        return False

    def set_values(self, brightness: int, temperature: int, on: bool = True) -> None:
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
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._on_activate)
        self._panel = None
        self._focus_poll_id = None

    def _dismiss(self) -> None:
        if self._focus_poll_id is not None:
            GLib.source_remove(self._focus_poll_id)
            self._focus_poll_id = None
        if self._panel is not None:
            self._panel.close()
            self._panel = None

    def _on_activate(self, app: Adw.Application) -> None:
        if self._panel is not None:
            self._dismiss()
            return

        # Compute desired position
        cursor_x, _ = _get_cursor_pos()
        monitor = _get_focused_monitor()
        mon_x = monitor.get("x", 0)
        mon_width = monitor.get("width", 1920)

        panel_x = cursor_x - (PANEL_WIDTH // 2)
        panel_x = max(mon_x + SCREEN_EDGE_PAD,
                      min(panel_x, mon_x + mon_width - PANEL_WIDTH - SCREEN_EDGE_PAD))
        panel_y = WAYBAR_HEIGHT + PANEL_GAP

        # Set up hyprland window rules before the window appears
        _setup_window_rules()

        # Create the panel window
        panel = Gtk.Window(application=app)
        panel.set_title("elgato-panel")
        panel.set_default_size(PANEL_WIDTH, -1)
        panel.set_resizable(False)
        panel.set_decorated(False)
        self._panel = panel

        panel.connect("close-request", self._on_close)

        # Escape key
        esc = Gtk.EventControllerKey()
        esc.connect("key-pressed", self._on_key_pressed)
        panel.add_controller(esc)

        # Build content
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        panel.set_child(main_box)

        lights = _load_lights()
        self.controls: dict[str, LightControl] = {}
        for light in lights:
            ctrl = LightControl(light["name"], light["host"], light["port"])
            self.controls[light["name"]] = ctrl
            main_box.append(ctrl.frame)

        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        preset_box.set_halign(Gtk.Align.CENTER)
        preset_box.set_margin_top(4)

        presets = _load_presets()
        for name in ["webcam", "video", "bright", "dim", "warm", "cool"]:
            if name not in presets:
                continue
            btn = Gtk.Button(label=name.capitalize())
            btn.add_css_class("preset-btn")
            btn.connect("clicked", partial(self._on_preset, name=name, preset=presets[name]))
            preset_box.append(btn)

        off_btn = Gtk.Button(label="Off")
        off_btn.add_css_class("destructive-action")
        off_btn.connect("clicked", self._on_all_off)
        preset_box.append(off_btn)
        main_box.append(preset_box)

        # CSS
        css = Gtk.CssProvider()
        css.load_from_string(
            """
            window {
                background-color: rgba(30, 30, 46, 0.98);
                border-radius: 0 0 12px 12px;
                border: 1px solid rgba(122, 162, 247, 0.3);
                border-top: none;
            }
            .light-name { font-weight: bold; font-size: 14px; color: #cdd6f4; }
            .light-frame { margin-bottom: 4px; }
            .preset-btn { min-width: 50px; }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        panel.present()

        # Position via hyprctl after the window is mapped
        # Small delay to ensure Hyprland has registered the window
        GLib.timeout_add(50, self._position_panel, panel_x, panel_y)

        # Start focus polling after a grace period (500ms for the window to settle)
        GLib.timeout_add(500, self._start_focus_poll)

    def _position_panel(self, x: int, y: int) -> bool:
        """Move the panel to position via hyprctl."""
        _move_window("elgato-panel", x, y)
        # Re-focus after move
        _hyprctl_dispatch(f"focuswindow title:elgato-panel")
        return False

    def _start_focus_poll(self) -> bool:
        """Start polling for focus loss — if our panel isn't the active window, close."""
        self._focus_poll_id = GLib.timeout_add(200, self._check_focus)
        return False

    def _check_focus(self) -> bool:
        """Poll: is our panel still the active window?"""
        if self._panel is None:
            return False
        try:
            active = _hyprctl_j("activewindow")
            if active.get("class") != APP_ID:
                # Lost focus — dismiss
                GLib.idle_add(self._dismiss)
                return False
        except Exception:
            pass
        return True  # keep polling

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._dismiss()
            return True
        return False

    def _on_close(self, win: Gtk.Window) -> bool:
        self._panel = None
        if self._focus_poll_id is not None:
            GLib.source_remove(self._focus_poll_id)
            self._focus_poll_id = None
        return False

    def _on_preset(self, btn: Gtk.Button, name: str, preset: dict) -> None:
        for light_name, ctrl in self.controls.items():
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
