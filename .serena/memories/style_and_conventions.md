# Style and Conventions

## Python
- `from __future__ import annotations` at top of every file
- Type hints on function signatures
- Minimal docstrings — only where non-obvious
- Private functions prefixed with `_`
- snake_case everywhere
- f-strings preferred
- No formal linter config yet — follow existing style

## GTK/Tray Code (tray.py)
- Uses stdlib only (no httpx) — must run on system python
- urllib.request for HTTP, tomllib for TOML, json for JSON
- GLib.timeout_add for async scheduling within GTK main loop
- Debounced slider updates (150ms)

## General
- Keep solutions simple, avoid over-engineering
- Hardcoded defaults for the two known lights, config file optional
- Presets support per-light overrides (e.g., webcam preset has different brightness for left/right)
