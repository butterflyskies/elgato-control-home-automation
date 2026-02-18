# Suggested Commands

## Development
- `uv run elgato status` — show light states
- `uv run elgato toggle` — toggle all lights
- `uv run elgato flash` — flash lights
- `uv run elgato-waybar` — output waybar JSON
- `uv run elgato-mcp` — start MCP server

## Tray/Panel (system python — not through uv)
- `elgato-tray` — start combined tray daemon + panel
- `elgato-panel` — toggle panel (activates running tray, or standalone)

## Install
- `uv tool install -e ".[mcp]"` — global CLI install
- Tray/panel use wrapper scripts in `~/.local/bin/` (system python)

## Git
- `GIT_CONFIG_GLOBAL=~/.gitconfig.ai git ...` — all git operations

## Testing
- No formal test suite yet — verify against real lights
- `uv run python -c "from elgato_keylight.client import KeyLight; ..."` — quick checks
