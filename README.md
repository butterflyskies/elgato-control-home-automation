# elgato-keylight

Control Elgato Key Lights from CLI, waybar, and Claude Code (MCP).

## Install

```bash
# Development
uv sync

# Global CLI
uv tool install -e ".[mcp]"
```

## CLI

```bash
elgato status                # Show all lights
elgato on                    # Turn all on
elgato off                   # Turn all off
elgato toggle                # Toggle on/off
elgato brightness 75         # Set brightness (0-100)
elgato brightness-up         # +10 brightness
elgato brightness-down       # -10 brightness
elgato temperature 200       # Set color temp (143-344)
elgato preset webcam         # Apply preset (per-light values)
elgato identify              # Flash to identify
elgato -l right status       # Target specific light

# Effects
elgato flash                 # Flash on/off
elgato pulse                 # Smooth brightness pulse
elgato celebrate             # Color temperature dance
elgato alert                 # Urgent attention flash
elgato mood focus            # Set mood (cozy/focus/relax/energize/movie)
```

## Waybar

Add to `~/.config/waybar/config.jsonc`:

```jsonc
"custom/lights": {
    "exec": "elgato-waybar",
    "return-type": "json",
    "interval": 30,
    "on-click": "elgato toggle",
    "on-click-right": "elgato preset video",
    "on-scroll-up": "elgato brightness-up",
    "on-scroll-down": "elgato brightness-down"
}
```

Add to `~/.config/waybar/style.css`:

```css
#custom-lights {
    color: #7aa2f7;
}
#custom-lights.off {
    color: #565f89;
}
#custom-lights.mixed {
    color: #e0af68;
}
```

## MCP Server

Add to `~/.claude.json`:

```json
{
    "mcpServers": {
        "elgato-keylight": {
            "command": "uv",
            "args": ["run", "--directory", "/path/to/elgato-control-home-automation", "--extra", "mcp", "elgato-mcp"]
        }
    }
}
```

## Config

Config lives at `~/.config/elgato-keylight/config.toml`. Presets support per-light overrides:

```toml
[presets.webcam]
brightness = 32       # fallback for unnamed lights
temperature = 179

[presets.webcam.right]
brightness = 18       # right light gets its own values
temperature = 181

[presets.webcam.left]
brightness = 46       # left light gets its own values
temperature = 177
```
