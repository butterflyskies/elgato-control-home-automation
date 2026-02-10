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
    """Load lights from config file, falling back to mDNS discovery."""
    config_path = Path.home() / ".config" / "elgato-keylight" / "config.toml"
    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        lights = data.get("lights", [])
        if lights:
            return [{"name": l["name"], "host": l["host"], "port": l.get("port", 9123)} for l in lights]

    return _discover_lights()


def _discover_lights() -> list[dict]:
    """Discover Elgato lights via mDNS (avahi-browse)."""
    try:
        out = subprocess.check_output(
            ["avahi-browse", "-rpt", "_elg._tcp"],
            timeout=5, stderr=subprocess.DEVNULL,
        ).decode()
    except Exception:
        return []

    lights = []
    seen = set()
    for line in out.splitlines():
        # Resolved IPv4 lines: =;iface;IPv4;name;_elg._tcp;domain;hostname;ip;port;txt...
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
        # Extract device ID from TXT record: "id=3C:6A:9D:1A:36:45"
        device_id = ""
        txt = ";".join(parts[9:]) if len(parts) > 9 else ""
        for token in txt.replace('"', " ").split():
            if token.startswith("id="):
                device_id = token[3:]
                break
        lights.append({"name": name.lower(), "host": host, "port": port, "id": device_id})

    lights.sort(key=lambda l: l["name"])
    return lights


def _load_presets() -> dict[str, dict]:
    config_path = Path.home() / ".config" / "elgato-keylight" / "config.toml"
    defaults = {
        "webcam": {"brightness": 32, "temperature": 179,
                    "3C:6A:9D:1A:36:45": {"brightness": 18, "temperature": 181},
                    "3C:6A:9D:1A:36:46": {"brightness": 46, "temperature": 177}},
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
            return presets
    return defaults


# --- hyprctl helpers ---


def _hyprctl_j(cmd: str) -> dict | list:
    out = subprocess.check_output(["hyprctl", cmd, "-j"], timeout=1)
    return json.loads(out)


def _hyprctl_dispatch(cmd: str) -> None:
    subprocess.run(["hyprctl", "dispatch", cmd], timeout=1,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _hyprctl_batch(commands: list[str]) -> None:
    """Run multiple hyprctl commands atomically in a single IPC call."""
    batch = " ; ".join(commands)
    subprocess.run(["hyprctl", "--batch", batch], timeout=1,
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

    def __init__(self, name: str, host: str, port: int, device_id: str = ""):
        self.name = name
        self.host = host
        self.port = port
        self.device_id = device_id
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
        self._updating_master = False
        self._master_switch: Gtk.Switch | None = None

    # --- Lifecycle ---

    def _on_startup(self, app: Adw.Application) -> None:
        self._lights = _load_lights()
        self._presets = _load_presets()

        if self._start_tray:
            self._setup_tray()
            self.hold()  # Keep alive with no visible windows

        self._build_panel()

        # Map the panel once off-screen. Static hyprland rules handle
        # float/pin/noanim/noborder/noshadow. Future show/hide just moves it.
        self._panel_window.present()
        GLib.idle_add(self._park_panel_offscreen)
        GLib.idle_add(self._poll_status)
        GLib.timeout_add_seconds(POLL_SECONDS, self._poll_status)

    def _on_activate(self, app: Adw.Application) -> None:
        if self._skip_first_activate:
            self._skip_first_activate = False
            return
        self._toggle_panel()

    def _park_panel_offscreen(self) -> bool:
        """After initial map, park the panel off-screen."""
        _hyprctl_dispatch(f"movewindowpixel exact 99999 99999,class:{APP_ID}")
        return False

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

        self._register_with_watcher()

        # Re-register when the watcher restarts (e.g. waybar reload)
        Gio.bus_watch_name_on_connection(
            bus, "org.kde.StatusNotifierWatcher",
            Gio.BusNameWatcherFlags.NONE,
            self._on_watcher_appeared,
            None,
        )

    def _register_with_watcher(self) -> None:
        try:
            self._bus.call_sync(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self._bus_name,)),
                None, Gio.DBusCallFlags.NONE, -1, None,
            )
            self._tray_registered = True
        except Exception:
            self._tray_registered = False

    def _on_watcher_appeared(self, conn, name, owner) -> None:
        self._register_with_watcher()

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
            "Title": GLib.Variant("s", ""),
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
                on = state.get("on", 0)
                if on:
                    any_on = True
                ctrl = self._controls.get(light["name"])
                if ctrl:
                    ctrl.refresh(state.get("brightness", 50), state.get("temperature", 200), bool(on))
            except Exception:
                pass

        if any_on != self._any_on:
            self._any_on = any_on
            self._icon_name = ICON_ON if any_on else ICON_OFF
            self._sni_emit("NewIcon")

        if self._master_switch is not None:
            self._updating_master = True
            self._master_switch.set_active(any_on)
            self._updating_master = False

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

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(16)
        main_box.set_margin_start(16)
        main_box.set_margin_end(16)
        window.set_child(main_box)

        # Title header with master switch
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Key Light Control")
        title.add_css_class("panel-title")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        title_box.append(title)

        self._master_switch = Gtk.Switch()
        self._master_switch.set_valign(Gtk.Align.CENTER)
        self._master_switch.connect("state-set", self._on_master_toggle)
        title_box.append(self._master_switch)
        title_box.set_margin_bottom(4)
        main_box.append(title_box)

        # Per-light controls
        for light in self._lights:
            ctrl = LightControl(light["name"], light["host"], light["port"], light.get("id", ""))
            self._controls[light["name"]] = ctrl
            main_box.append(ctrl.frame)

        # Presets section
        presets_label = Gtk.Label(label="Presets")
        presets_label.add_css_class("section-label")
        presets_label.set_halign(Gtk.Align.START)
        presets_label.set_margin_top(4)
        main_box.append(presets_label)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("preset-list")
        listbox.add_css_class("boxed-list")

        for name, preset in self._presets.items():
            row = self._make_preset_row(name, preset)
            listbox.append(row)

        # Off row
        off_row = Gtk.ListBoxRow()
        off_row.add_css_class("preset-off-row")
        off_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        off_box.set_margin_top(8)
        off_box.set_margin_bottom(8)
        off_box.set_margin_start(12)
        off_box.set_margin_end(12)
        off_label = Gtk.Label(label="All Off")
        off_label.add_css_class("preset-off-label")
        off_label.set_hexpand(True)
        off_label.set_halign(Gtk.Align.CENTER)
        off_box.append(off_label)
        off_row.set_child(off_box)
        listbox.append(off_row)

        listbox.connect("row-activated", self._on_preset_row_activated)
        main_box.append(listbox)

        # Quit link (only in tray daemon mode)
        if self._start_tray:
            quit_btn = Gtk.Button(label="Quit Tray")
            quit_btn.add_css_class("quit-link")
            quit_btn.set_halign(Gtk.Align.END)
            quit_btn.set_margin_top(4)
            quit_btn.connect("clicked", lambda _: self.quit())
            main_box.append(quit_btn)

        css = Gtk.CssProvider()
        css.load_from_string("""
            window {
                background-color: rgba(30, 30, 46, 0.65);
                border-radius: 0 0 12px 12px;
                border: 1px solid rgba(122, 162, 247, 0.3);
                border-top: none;
            }
            .panel-title {
                font-weight: bold;
                font-size: 15px;
                color: #cdd6f4;
                letter-spacing: 0.5px;
            }
            .section-label {
                font-size: 11px;
                font-weight: bold;
                color: rgba(205, 214, 244, 0.5);
                letter-spacing: 1px;
                text-transform: uppercase;
            }
            .light-name { font-weight: bold; font-size: 14px; color: #cdd6f4; }
            .light-frame { margin-bottom: 4px; }
            .preset-list {
                background: transparent;
                border-radius: 8px;
            }
            .preset-list row {
                border-radius: 6px;
                transition: background-color 150ms ease;
            }
            .preset-list row:hover {
                background-color: rgba(122, 162, 247, 0.08);
            }
            .preset-name {
                font-weight: 600;
                font-size: 13px;
                color: #cdd6f4;
            }
            .preset-detail {
                font-size: 12px;
                color: rgba(205, 214, 244, 0.5);
            }
            .preset-off-row:hover {
                background-color: rgba(243, 139, 168, 0.12);
            }
            .preset-off-label {
                font-weight: 600;
                font-size: 13px;
                color: #f38ba8;
            }
            .quit-link {
                background: none;
                border: none;
                box-shadow: none;
                font-size: 11px;
                color: rgba(205, 214, 244, 0.35);
                padding: 2px 8px;
                min-height: 0;
            }
            .quit-link:hover {
                color: rgba(205, 214, 244, 0.6);
            }
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

        # Window is always mapped — just move it into place and focus
        _hyprctl_batch([
            f"dispatch movewindowpixel exact {panel_x} {panel_y},class:{APP_ID}",
            f"dispatch focuswindow class:{APP_ID}",
        ])
        self._panel_visible = True
        GLib.timeout_add(700, self._start_focus_poll)

    def _hide_panel(self) -> None:
        poll_id = self._focus_poll_id
        self._focus_poll_id = None
        if poll_id is not None:
            GLib.source_remove(poll_id)
        # Move off-screen instead of unmapping — avoids re-map placement issues
        _hyprctl_dispatch(f"movewindowpixel exact 99999 99999,class:{APP_ID}")
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


    def _on_master_toggle(self, switch: Gtk.Switch, state: bool) -> bool:
        if self._updating_master:
            return False
        on = 1 if state else 0
        for ctrl in self._controls.values():
            ctrl.current_on = on
            ctrl._updating_from_api = True
            ctrl.power_switch.set_active(state)
            ctrl._updating_from_api = False
            try:
                _set_light_state(ctrl.host, ctrl.port, on, ctrl.current_brightness, ctrl.current_temperature)
            except Exception:
                pass
        return False

    def _on_panel_close(self, win: Gtk.Window) -> bool:
        self._hide_panel()
        return True  # Prevent destruction — we reuse the window

    def _make_preset_row(self, name: str, preset: dict) -> Gtk.ListBoxRow:
        """Build a ListBoxRow for a preset with per-device brightness/temperature."""
        row = Gtk.ListBoxRow()
        row._preset_name = name
        row._preset_data = preset

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        outer.set_margin_top(8)
        outer.set_margin_bottom(8)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        # Preset name on top line, per-device details below
        for i, light in enumerate(self._lights):
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

            if i == 0:
                # First line: preset name on the left
                label = Gtk.Label(label=name.capitalize())
                label.add_css_class("preset-name")
                label.set_halign(Gtk.Align.START)
                label.set_hexpand(True)
                line.append(label)
            else:
                # Subsequent lines: empty spacer on the left
                spacer = Gtk.Label(label="")
                spacer.set_hexpand(True)
                line.append(spacer)

            # Resolve per-device override by device ID
            device_id = light.get("id", "")
            device_settings = preset.get(device_id) if device_id else None
            if isinstance(device_settings, dict):
                bri = device_settings["brightness"]
                temp = device_settings["temperature"]
            else:
                bri = preset.get("brightness", 50)
                temp = preset.get("temperature", 200)

            kelvin = _temp_to_kelvin(temp)
            detail = Gtk.Label(label=f"{light['name']}  {bri}%  {kelvin}K")
            detail.add_css_class("preset-detail")
            detail.set_halign(Gtk.Align.END)
            line.append(detail)

            outer.append(line)

        row.set_child(outer)
        return row

    def _on_preset_row_activated(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if hasattr(row, "_preset_data"):
            preset = row._preset_data
            for light_name, ctrl in self._controls.items():
                # Look up per-device override by device ID
                device_settings = preset.get(ctrl.device_id) if ctrl.device_id else None
                if isinstance(device_settings, dict):
                    ctrl.set_values(device_settings["brightness"], device_settings["temperature"])
                else:
                    ctrl.set_values(preset.get("brightness", 50), preset.get("temperature", 200))
        else:
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
