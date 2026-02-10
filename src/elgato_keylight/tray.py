"""Combined system tray icon + control panel for Elgato Key Lights.

Tray icon uses raw StatusNotifierItem D-Bus protocol (no AppIndicator3).
Panel uses GTK4/Adwaita, pre-built at startup and shown/hidden on click.

Entry points:
  elgato-tray  → starts daemon (tray + hidden panel, hot)
  elgato-panel → toggles panel (activates running tray, or starts standalone)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tomllib
import urllib.request
from functools import partial
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID = "dev.butterflysky.elgato-panel"
PANEL_WIDTH = 380
WAYBAR_HEIGHT = 36
PANEL_GAP = 4
SCREEN_EDGE_PAD = 8
ICON_ON = "display-brightness-symbolic"
ICON_OFF = "night-light-symbolic"
POLL_SECONDS = 10

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewStatus">
      <arg type="s"/>
    </signal>
  </interface>
</node>
"""


# --- HTTP helpers (stdlib only — no httpx, runs on system python) ---


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


# --- hyprctl helpers ---


def _hyprctl_j(cmd: str) -> dict | list:
    out = subprocess.check_output(["hyprctl", cmd, "-j"], timeout=1)
    return json.loads(out)


def _hyprctl_dispatch(cmd: str) -> None:
    subprocess.run(["hyprctl", "dispatch", cmd], timeout=1,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _hyprctl_keyword(key: str, value: str) -> None:
    subprocess.run(["hyprctl", "keyword", key, value], timeout=1,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _get_cursor_pos() -> tuple[int, int]:
    try:
        data = _hyprctl_j("cursorpos")
        return data["x"], data["y"]
    except Exception:
        return 960, 0


def _get_focused_monitor() -> dict:
    try:
        monitors = _hyprctl_j("monitors")
        for m in monitors:
            if m.get("focused"):
                return m
        return monitors[0]
    except Exception:
        return {"width": 1920, "height": 1080, "x": 0, "y": 0, "scale": 1.0, "transform": 0}


def _temp_to_kelvin(temp: int) -> int:
    return int(1_000_000 / temp) if temp > 0 else 0


# --- LightControl (per-light slider UI) ---


class LightControl:
    """Slider controls for a single light."""

    def __init__(self, name: str, host: str, port: int):
        self.name = name
        self.host = host
        self.port = port
        self._debounce_id: int | None = None
        self._updating_from_api = False
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
        self.brightness_scale.set_value(50)
        self.brightness_scale.set_hexpand(True)
        self.brightness_scale.connect("value-changed", self._on_slider_changed)
        bright_box.append(self.brightness_scale)

        self.brightness_value = Gtk.Label(label="50%")
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
        self.temp_scale.set_value(200)
        self.temp_scale.set_hexpand(True)
        self.temp_scale.set_inverted(True)
        self.temp_scale.connect("value-changed", self._on_slider_changed)
        temp_box.append(self.temp_scale)

        self.temp_value = Gtk.Label(label=f"{_temp_to_kelvin(200)}K")
        self.temp_value.set_size_request(55, -1)
        temp_box.append(self.temp_value)
        box.append(temp_box)

    def refresh(self, brightness: int, temperature: int, on: bool) -> None:
        """Update UI from light state without sending an API call back."""
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

    def _on_power_toggle(self, switch: Gtk.Switch, state: bool) -> bool:
        if self._updating_from_api:
            return False
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
        """Update UI and send to light (used by preset buttons)."""
        self.refresh(brightness, temperature, on)
        self._schedule_update()


# --- Combined App ---


class ElgatoApp(Adw.Application):
    """Combined tray icon and control panel.

    Uses Adw.Application for single-instance behavior:
    - First launch: registers tray + builds panel (hidden)
    - Subsequent launches: activate → toggle panel
    """

    def __init__(self, start_tray: bool = True):
        super().__init__(application_id=APP_ID)
        self._start_tray = start_tray
        self.connect("startup", self._on_startup)
        self.connect("activate", self._on_activate)
        self._panel_window: Gtk.Window | None = None
        self._panel_visible = False
        self._focus_poll_id: int | None = None
        self._skip_first_activate = start_tray
        self._tray_registered = False
        self._bus: Gio.DBusConnection | None = None
        self._any_on = False
        self._icon_name = ICON_OFF
        self._lights: list[dict] = []
        self._presets: dict[str, dict] = {}
        self._controls: dict[str, LightControl] = {}

    # --- Lifecycle ---

    def _on_startup(self, app: Adw.Application) -> None:
        self._lights = _load_lights()
        self._presets = _load_presets()

        if self._start_tray:
            self._setup_tray()
            self.hold()  # Keep alive with no visible windows

        self._build_panel()
        self._poll_status()
        GLib.timeout_add_seconds(POLL_SECONDS, self._poll_status)

    def _on_activate(self, app: Adw.Application) -> None:
        if self._skip_first_activate:
            self._skip_first_activate = False
            return
        self._toggle_panel()

    # --- SNI Tray ---

    def _setup_tray(self) -> None:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._bus = bus

        node = Gio.DBusNodeInfo.new_for_xml(SNI_XML)
        bus.register_object(
            "/StatusNotifierItem",
            node.interfaces[0],
            self._sni_method_call,
            self._sni_get_property,
            None,
        )

        self._bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        Gio.bus_own_name_on_connection(
            bus, self._bus_name,
            Gio.BusNameOwnerFlags.NONE, None, None,
        )

        bus.call_sync(
            "org.kde.StatusNotifierWatcher",
            "/StatusNotifierWatcher",
            "org.kde.StatusNotifierWatcher",
            "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self._bus_name,)),
            None, Gio.DBusCallFlags.NONE, -1, None,
        )
        self._tray_registered = True

    def _sni_method_call(self, conn, sender, path, iface, method, params, invocation):
        if method in ("Activate", "ContextMenu"):
            self._toggle_panel()
        elif method == "SecondaryActivate":
            subprocess.Popen(["elgato", "toggle"])
            GLib.timeout_add(500, self._poll_status)
        elif method == "Scroll":
            delta, orientation = params.unpack()
            if orientation == "vertical":
                cmd = "brightness-up" if delta > 0 else "brightness-down"
                subprocess.Popen(["elgato", cmd])
                GLib.timeout_add(300, self._poll_status)
        invocation.return_value(None)

    def _sni_get_property(self, conn, sender, path, iface, prop):
        props = {
            "Category": GLib.Variant("s", "Hardware"),
            "Id": GLib.Variant("s", "elgato-keylight"),
            "Title": GLib.Variant("s", "Elgato Key Lights"),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", self._icon_name),
            "IconThemePath": GLib.Variant("s", ""),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", "/NO_DBUSMENU"),
        }
        return props.get(prop)

    def _sni_emit(self, signal_name: str) -> None:
        if self._tray_registered and self._bus:
            self._bus.emit_signal(
                None, "/StatusNotifierItem",
                "org.kde.StatusNotifierItem", signal_name, None,
            )

    # --- Status Polling ---

    def _poll_status(self) -> bool:
        any_on = False
        for light in self._lights:
            try:
                state = _get_light_state(light["host"], light["port"])
                if state.get("on", 0):
                    any_on = True
            except Exception:
                pass

        if any_on != self._any_on:
            self._any_on = any_on
            self._icon_name = ICON_ON if any_on else ICON_OFF
            self._sni_emit("NewIcon")

        return True

    # --- Panel UI ---

    def _build_panel(self) -> None:
        window = Gtk.Window(application=self)
        window.set_title("elgato-panel")
        window.set_default_size(PANEL_WIDTH, -1)
        window.set_resizable(False)
        window.set_decorated(False)
        window.connect("close-request", self._on_panel_close)

        esc = Gtk.EventControllerKey()
        esc.connect("key-pressed", self._on_key_pressed)
        window.add_controller(esc)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        window.set_child(main_box)

        for light in self._lights:
            ctrl = LightControl(light["name"], light["host"], light["port"])
            self._controls[light["name"]] = ctrl
            main_box.append(ctrl.frame)

        # Preset buttons in a FlowBox so they wrap within PANEL_WIDTH
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(True)
        flow.set_max_children_per_line(4)
        flow.set_min_children_per_line(3)
        flow.set_column_spacing(6)
        flow.set_row_spacing(6)
        flow.set_halign(Gtk.Align.CENTER)
        flow.set_margin_top(4)

        for name in ["webcam", "video", "bright", "dim", "warm", "cool"]:
            if name not in self._presets:
                continue
            btn = Gtk.Button(label=name.capitalize())
            btn.add_css_class("preset-btn")
            btn.connect("clicked", partial(self._on_preset, name=name, preset=self._presets[name]))
            flow.insert(btn, -1)

        off_btn = Gtk.Button(label="Off")
        off_btn.add_css_class("destructive-action")
        off_btn.connect("clicked", self._on_all_off)
        flow.insert(off_btn, -1)
        main_box.append(flow)

        css = Gtk.CssProvider()
        css.load_from_string("""
            window {
                background-color: rgba(30, 30, 46, 0.98);
                border-radius: 0 0 12px 12px;
                border: 1px solid rgba(122, 162, 247, 0.3);
                border-top: none;
            }
            .light-name { font-weight: bold; font-size: 14px; color: #cdd6f4; }
            .light-frame { margin-bottom: 4px; }
            .preset-btn { min-width: 50px; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._panel_window = window

    # --- Panel Show/Hide ---

    def _toggle_panel(self) -> None:
        if self._panel_visible:
            self._hide_panel()
        else:
            self._show_panel()

    def _show_panel(self) -> None:
        # Refresh sliders from live light state
        for light in self._lights:
            ctrl = self._controls.get(light["name"])
            if ctrl:
                try:
                    state = _get_light_state(light["host"], light["port"])
                    ctrl.refresh(
                        state.get("brightness", 50),
                        state.get("temperature", 200),
                        on=bool(state.get("on", 0)),
                    )
                except Exception:
                    pass

        # Calculate position centered on cursor, below waybar, clamped to monitor
        cursor_x, _ = _get_cursor_pos()
        monitor = _get_focused_monitor()
        mon_x = monitor.get("x", 0)
        mon_y = monitor.get("y", 0)
        scale = monitor.get("scale", 1.0)
        transform = monitor.get("transform", 0)
        pixel_w = monitor.get("width", 1920)
        if transform % 2 == 1:
            pixel_w = monitor.get("height", 1080)
        eff_w = int(pixel_w / scale)

        panel_x = cursor_x - PANEL_WIDTH // 2
        panel_x = max(mon_x + SCREEN_EDGE_PAD,
                      min(panel_x, mon_x + eff_w - PANEL_WIDTH - SCREEN_EDGE_PAD))
        panel_y = mon_y + WAYBAR_HEIGHT + PANEL_GAP

        # Set Hyprland window rules with exact position (applied at window map time)
        _hyprctl_keyword("windowrulev2", f"unset,class:{APP_ID}")
        for rule in [
            f"float,class:{APP_ID}",
            f"pin,class:{APP_ID}",
            f"noanim,class:{APP_ID}",
            f"noborder,class:{APP_ID}",
            f"noshadow,class:{APP_ID}",
            f"move {panel_x} {panel_y},class:{APP_ID}",
        ]:
            _hyprctl_keyword("windowrulev2", rule)

        self._panel_window.present()
        self._panel_visible = True

        # After Hyprland maps the window, focus it and ensure position
        GLib.timeout_add(50, self._post_show, panel_x, panel_y)
        GLib.timeout_add(700, self._start_focus_poll)

    def _post_show(self, x: int, y: int) -> bool:
        """Focus panel and reinforce position after Hyprland maps it."""
        _hyprctl_dispatch(f"focuswindow class:{APP_ID}")
        # Belt and suspenders: also move via dispatch in case the rule didn't apply
        _hyprctl_dispatch(f"movewindowpixel exact {x} {y},class:{APP_ID}")
        return False

    def _hide_panel(self) -> None:
        poll_id = self._focus_poll_id
        self._focus_poll_id = None
        if poll_id is not None:
            GLib.source_remove(poll_id)
        if self._panel_window:
            self._panel_window.set_visible(False)
        self._panel_visible = False

    # --- Focus Polling ---

    def _start_focus_poll(self) -> bool:
        if not self._panel_visible:
            return False
        self._focus_poll_id = GLib.timeout_add(200, self._check_focus)
        return False

    def _check_focus(self) -> bool:
        if not self._panel_visible:
            self._focus_poll_id = None
            return False
        try:
            active = _hyprctl_j("activewindow")
            if active.get("class") != APP_ID:
                self._focus_poll_id = None
                GLib.idle_add(self._hide_panel)
                return False
        except Exception:
            pass
        return True

    # --- Panel Event Handlers ---

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._hide_panel()
            return True
        return False

    def _on_panel_close(self, win: Gtk.Window) -> bool:
        self._hide_panel()
        return True  # Prevent destruction — we reuse the window

    def _on_preset(self, btn: Gtk.Button, name: str, preset: dict) -> None:
        for light_name, ctrl in self._controls.items():
            if light_name in preset and isinstance(preset[light_name], dict):
                override = preset[light_name]
                ctrl.set_values(override["brightness"], override["temperature"])
            else:
                ctrl.set_values(preset.get("brightness", 50), preset.get("temperature", 200))

    def _on_all_off(self, btn: Gtk.Button) -> None:
        for ctrl in self._controls.values():
            ctrl.set_values(ctrl.current_brightness, ctrl.current_temperature, on=False)


def main():
    """Start combined tray + panel daemon."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = ElgatoApp(start_tray=True)
    app.run(None)


def main_panel():
    """Toggle the panel. Activates running tray, or starts standalone (no tray)."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = ElgatoApp(start_tray=False)
    app.run(None)


if __name__ == "__main__":
    main()
