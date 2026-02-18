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
  models.py            # LightState, DeviceInfo, LightConfig, Preset dataclasses
  config.py            # TOML config loader (~/.config/elgato-keylight/config.toml)
  discovery.py         # mDNS light discovery via avahi-browse (stdlib only)
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
PyGObject builds from source — needs system dev headers (gobject-introspection-devel, cairo-devel, gtk4-devel, libadwaita-devel).

## Key Design Decisions
- No hardcoded light IPs — all paths use mDNS discovery as fallback when no config file exists
- Config at `~/.config/elgato-keylight/config.toml` — presets keyed by device hardware ID (from avahi TXT `id=...` field)
- `Preset.to_state()` resolves per-light overrides by device ID first, then by light name
- Tray + panel are a single `Adw.Application` process (combined for instant panel show/hide)
- Raw D-Bus SNI protocol (not AppIndicator3) gives direct click handling
- PyGObject installed as pip dependency via `[gui]` extra
- Five built-in presets (bright/dim/warm/cool/video); config presets merge on top
- Panel always-mapped off-screen (99999,99999), moved to tray icon position on show
- Tokyo Night theme colors, accent #7aa2f7
