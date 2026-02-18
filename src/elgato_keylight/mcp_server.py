"""FastMCP server for controlling Elgato Key Lights from Claude Code."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from elgato_keylight.client import KeyLight
from elgato_keylight.config import get_lights, get_preset, list_presets
from elgato_keylight.effects import (
    alert as alert_effect,
    celebration,
    dim_slowly,
    flash as flash_effect,
    list_moods,
    pulse as pulse_effect,
    set_mood as set_mood_effect,
)

mcp = FastMCP(
    "elgato-keylight",
    instructions="Control Elgato Key Lights — brightness, temperature, effects, and moods",
)


async def _get_clients(light_names: list[str] | None = None) -> list[KeyLight]:
    configs = get_lights(light_names)
    return [KeyLight(c) for c in configs]


async def _close_all(clients: list[KeyLight]) -> None:
    for c in clients:
        await c.close()


@mcp.tool()
async def get_light_status(light_names: list[str] | None = None) -> str:
    """Get the current status of all (or specified) lights.

    Args:
        light_names: Optional list of light names to query (e.g. ["left", "right"]).
                     If not provided, queries all configured lights.
    """
    clients = await _get_clients(light_names)
    results = []
    try:
        for c in clients:
            try:
                state = await c.get_state()
                info = await c.get_info()
                results.append(
                    f"{c.name} ({info.display_name or info.product_name}): "
                    f"{'on' if state.on else 'off'}, "
                    f"brightness={state.brightness}%, "
                    f"temp={state.temperature} (~{state.temperature_kelvin}K)"
                )
            except Exception as e:
                results.append(f"{c.name}: error — {e}")
    finally:
        await _close_all(clients)
    return "\n".join(results)


@mcp.tool()
async def turn_on(light_names: list[str] | None = None) -> str:
    """Turn on all (or specified) lights.

    Args:
        light_names: Optional list of light names to turn on.
    """
    clients = await _get_clients(light_names)
    try:
        for c in clients:
            await c.turn_on()
    finally:
        await _close_all(clients)
    return "Lights turned on."


@mcp.tool()
async def turn_off(light_names: list[str] | None = None) -> str:
    """Turn off all (or specified) lights.

    Args:
        light_names: Optional list of light names to turn off.
    """
    clients = await _get_clients(light_names)
    try:
        for c in clients:
            await c.turn_off()
    finally:
        await _close_all(clients)
    return "Lights turned off."


@mcp.tool()
async def toggle_lights(light_names: list[str] | None = None) -> str:
    """Toggle all (or specified) lights on/off.

    Args:
        light_names: Optional list of light names to toggle.
    """
    clients = await _get_clients(light_names)
    results = []
    try:
        for c in clients:
            state = await c.toggle()
            results.append(f"{c.name}: {'on' if state.on else 'off'}")
    finally:
        await _close_all(clients)
    return "\n".join(results)


@mcp.tool()
async def set_brightness(brightness: int, light_names: list[str] | None = None) -> str:
    """Set brightness of all (or specified) lights.

    Args:
        brightness: Brightness level 0-100.
        light_names: Optional list of light names.
    """
    clients = await _get_clients(light_names)
    try:
        for c in clients:
            await c.set_brightness(brightness)
    finally:
        await _close_all(clients)
    return f"Brightness set to {brightness}%."


@mcp.tool()
async def set_temperature(temperature: int, light_names: list[str] | None = None) -> str:
    """Set color temperature of all (or specified) lights.

    Args:
        temperature: Temperature in Elgato units (143=cool/7000K to 344=warm/2900K).
        light_names: Optional list of light names.
    """
    clients = await _get_clients(light_names)
    try:
        for c in clients:
            await c.set_temperature(temperature)
    finally:
        await _close_all(clients)
    return f"Temperature set to {temperature}."


@mcp.tool()
async def apply_preset(preset_name: str, light_names: list[str] | None = None) -> str:
    """Apply a named lighting preset.

    Available presets: bright, dim, warm, cool, video.

    Args:
        preset_name: Name of the preset to apply.
        light_names: Optional list of light names.
    """
    p = get_preset(preset_name)
    if p is None:
        available = ", ".join(list_presets().keys())
        return f"Unknown preset: {preset_name!r}. Available: {available}"

    clients = await _get_clients(light_names)
    try:
        for c in clients:
            await c.set_state(p.to_state(light_name=c.name, device_id=c.device_id, on=True))
    finally:
        await _close_all(clients)
    return f"Preset '{preset_name}' applied."


# --- Fun / attention tools ---


@mcp.tool()
async def flash_lights(times: int = 3, light_names: list[str] | None = None) -> str:
    """Flash the lights on/off to get attention or say hello! Restores original state.

    Args:
        times: Number of flashes (default 3).
        light_names: Optional list of light names.
    """
    clients = await _get_clients(light_names)
    try:
        await flash_effect(clients, times=times)
    finally:
        await _close_all(clients)
    return f"Flashed {times} times!"


@mcp.tool()
async def pulse_lights(cycles: int = 3, light_names: list[str] | None = None) -> str:
    """Smoothly pulse light brightness up and down. Restores original state.

    Args:
        cycles: Number of pulse cycles (default 3).
        light_names: Optional list of light names.
    """
    clients = await _get_clients(light_names)
    try:
        await pulse_effect(clients, cycles=cycles)
    finally:
        await _close_all(clients)
    return f"Pulsed {cycles} times!"


@mcp.tool()
async def celebrate() -> str:
    """Fun alternating color temperature dance! Perfect for celebrating a win.
    Restores original state when done.
    """
    clients = await _get_clients()
    try:
        await celebration(clients)
    finally:
        await _close_all(clients)
    return "Celebration complete!"


@mcp.tool()
async def alert_flash(flashes: int = 5, light_names: list[str] | None = None) -> str:
    """Urgent attention-getting flash at max brightness. Restores original state.

    Args:
        flashes: Number of alert flashes (default 5).
        light_names: Optional list of light names.
    """
    clients = await _get_clients(light_names)
    try:
        await alert_effect(clients, flashes=flashes)
    finally:
        await _close_all(clients)
    return "Alert sent!"


@mcp.tool()
async def dim_for_attention(light_names: list[str] | None = None) -> str:
    """Slowly dim lights to subtly get attention without being jarring.
    Restores original state.

    Args:
        light_names: Optional list of light names.
    """
    clients = await _get_clients(light_names)
    try:
        await dim_slowly(clients)
    finally:
        await _close_all(clients)
    return "Dim attention complete."


@mcp.tool()
async def set_mood_lighting(mood: str) -> str:
    """Set a mood lighting preset. This persists (does not restore previous state).

    Available moods: cozy, focus, relax, energize, movie.

    Args:
        mood: The mood to set.
    """
    available = list_moods()
    if mood not in available:
        return f"Unknown mood: {mood!r}. Available: {', '.join(available)}"
    clients = await _get_clients()
    try:
        await set_mood_effect(clients, mood)
    finally:
        await _close_all(clients)
    return f"Mood set to '{mood}'."


def main():
    """Entry point for the MCP server."""
    mcp.run()
