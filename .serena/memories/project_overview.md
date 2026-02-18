# Elgato Key Light Control System

## Purpose
Python toolset for controlling Elgato Key Lights from CLI, waybar, MCP server, system tray, and GTK4 control panel. Lights are discovered via mDNS (avahi-browse `_elg._tcp`) or configured in `~/.config/elgato-keylight/config.toml`.

## Tech Stack
- **Python 3.12+**, **uv** for project management, **hatchling** build backend
- **httpx** (async) for light HTTP API in CLI/waybar/MCP
- **click** for CLI subcommands
- **FastMCP** (`mcp` package) for Claude Code MCP server
- **GTK4/Adwaita** for control panel UI (PyGObject from PyPI via `[gui]` extra)
- **D-Bus StatusNotifierItem** protocol for system tray icon
- **urllib.request** for HTTP in tray.py (stdlib only, no httpx)

## Architecture
```
src/elgato_keylight/
  __init__.py          # re-exports
  models.py            # LightState, DeviceInfo, LightConfig dataclasses
  config.py            # TOML config loader (~/.config/elgato-keylight/config.toml)
  client.py            # KeyLight async HTTP client (httpx)
  effects.py           # flash, pulse, celebration, alert, dim, mood effects
  cli.py               # Click CLI (entry point: elgato)
  waybar.py            # Waybar JSON output (entry point: elgato-waybar)
  mcp_server.py        # FastMCP server (entry point: elgato-mcp)
  tray.py              # Combined tray icon + GTK4 control panel
  panel.py             # Thin wrapper that imports from tray.py
  _gui.py              # Entry point wrapper with graceful gi ImportError handling
```

## Entry Points
All entry points defined in pyproject.toml, installed via `uv tool install`:
- `elgato` (CLI), `elgato-waybar`, `elgato-mcp` — pure Python, no system deps
- `elgato-tray`, `elgato-panel` — require PyGObject (gui extra), routed through `_gui.py` wrapper with graceful ImportError handling

## Installation
```bash
uv tool install 'elgato-keylight[gui,mcp]'
```
PyGObject builds from source — needs system dev headers (gobject-introspection-devel, cairo-devel, gtk4-devel, libadwaita-devel). Must be built inside raptor distrobox on the user's immutable Bazzite host.

## Key Design Decisions
- Tray + panel are a single `Adw.Application` process (combined for instant panel show/hide)
- Raw D-Bus SNI protocol (not AppIndicator3) gives direct click handling
- PyGObject installed as pip dependency via `[gui]` extra (no longer requires system python shims)
- Config at `~/.config/elgato-keylight/config.toml` — presets keyed by device hardware ID (from avahi TXT `id=...` field)
- Lights discovered via mDNS (`avahi-browse -rpt _elg._tcp`) when no config lights section present
- Panel always-mapped off-screen (99999,99999), moved to tray icon position on show
- Static hyprland windowrulev2 rules for panel class `dev.butterflysky.elgato-panel`

## User's Environment
- Hyprland compositor on Wayland
- Waybar bar (custom/lights module removed — replaced by tray icon)
- Monitor: HDMI-A-1 (7680x2160 @ 0,0 scale 1.0), DP-2 (3840x1600 @ -1600,-1200 transform 3)
- Catppuccin theme, accent #7aa2f7
