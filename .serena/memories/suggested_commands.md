# Suggested Commands

## Development
- `uv run elgato status` — show light states
- `uv run elgato toggle` — toggle all lights
- `uv run elgato flash` — flash lights
- `uv run elgato-waybar` — output waybar JSON
- `uv run elgato-mcp` — start MCP server

## Install
- `uv tool install -e '.[gui,mcp]'` — full install (CLI + tray + MCP)
- `uv tool install -e '.[mcp]'` — CLI + MCP only
- `elgato-tray` — start combined tray daemon + panel
- `elgato-panel` — toggle panel (activates running tray, or standalone)

## Git
- `GIT_CONFIG_GLOBAL=~/.gitconfig.ai git ...` — all git operations

## Testing
- No formal test suite yet — verify against real lights
- `uv run python -c "from elgato_keylight.client import KeyLight; ..."` — quick checks
