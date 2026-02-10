"""Waybar custom module — outputs JSON for light status."""

from __future__ import annotations

import asyncio
import json
import sys

from elgato_keylight.client import KeyLight
from elgato_keylight.config import get_lights


async def _get_status() -> dict:
    configs = get_lights()
    clients = [KeyLight(c) for c in configs]

    states = []
    errors = []

    try:
        for c in clients:
            try:
                state = await c.get_state()
                states.append((c.name, state))
            except Exception:
                errors.append(c.name)
    finally:
        for c in clients:
            await c.close()

    if not states and errors:
        return {
            "text": " --",
            "tooltip": "All lights unreachable",
            "class": "error",
        }

    any_on = any(s.on for _, s in states)
    all_on = all(s.on for _, s in states)

    if all_on:
        css_class = "on"
    elif any_on:
        css_class = "mixed"
    else:
        css_class = "off"

    icon = "" if any_on else ""

    # Average brightness of lights that are on
    on_states = [(n, s) for n, s in states if s.on]
    if on_states:
        avg_brightness = sum(s.brightness for _, s in on_states) // len(on_states)
        text = f"{icon} {avg_brightness}%"
    else:
        text = f"{icon}"

    # Tooltip with per-light details
    tooltip_lines = []
    for name, state in states:
        status = "on" if state.on else "off"
        tooltip_lines.append(
            f"{name}: {status} | {state.brightness}% | ~{state.temperature_kelvin}K"
        )
    for name in errors:
        tooltip_lines.append(f"{name}: unreachable")

    return {
        "text": text,
        "tooltip": "\n".join(tooltip_lines),
        "class": css_class,
    }


def main():
    """Entry point for waybar module."""
    try:
        result = asyncio.run(_get_status())
    except Exception as e:
        result = {"text": " err", "tooltip": str(e), "class": "error"}
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
