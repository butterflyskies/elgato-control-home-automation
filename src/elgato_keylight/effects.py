"""Light effects — flash, pulse, celebration, alert, dim, mood."""

from __future__ import annotations

import asyncio

from elgato_keylight.client import KeyLight
from elgato_keylight.models import LightState


async def flash(lights: list[KeyLight], times: int = 3, interval: float = 0.3) -> None:
    """Flash lights on/off rapidly. Restores original state."""
    saved = await _save_states(lights)
    try:
        for _ in range(times):
            await _set_all(lights, LightState(on=True, brightness=100, temperature=200))
            await asyncio.sleep(interval)
            await _set_all(lights, LightState(on=False))
            await asyncio.sleep(interval)
    finally:
        await _restore_states(lights, saved)


async def pulse(lights: list[KeyLight], cycles: int = 3, step_ms: int = 50) -> None:
    """Smoothly pulse brightness up and down. Restores original state."""
    saved = await _save_states(lights)
    try:
        for _ in range(cycles):
            # Ramp up
            for b in range(10, 101, 5):
                await _set_all(lights, LightState(on=True, brightness=b, temperature=200))
                await asyncio.sleep(step_ms / 1000)
            # Ramp down
            for b in range(100, 9, -5):
                await _set_all(lights, LightState(on=True, brightness=b, temperature=200))
                await asyncio.sleep(step_ms / 1000)
    finally:
        await _restore_states(lights, saved)


async def celebration(lights: list[KeyLight]) -> None:
    """Fun alternating color temperature dance. Restores original state."""
    saved = await _save_states(lights)
    try:
        temps = [143, 200, 250, 300, 344]  # cool to warm sweep
        for _ in range(3):
            for temp in temps:
                await _set_all(lights, LightState(on=True, brightness=80, temperature=temp))
                await asyncio.sleep(0.2)
            for temp in reversed(temps):
                await _set_all(lights, LightState(on=True, brightness=80, temperature=temp))
                await asyncio.sleep(0.2)
    finally:
        await _restore_states(lights, saved)


async def alert(lights: list[KeyLight], flashes: int = 5) -> None:
    """Urgent attention-getting flash at max brightness. Restores original state."""
    saved = await _save_states(lights)
    try:
        for _ in range(flashes):
            await _set_all(lights, LightState(on=True, brightness=100, temperature=143))
            await asyncio.sleep(0.15)
            await _set_all(lights, LightState(on=False))
            await asyncio.sleep(0.15)
    finally:
        await _restore_states(lights, saved)


async def dim_slowly(lights: list[KeyLight], target: int = 10, steps: int = 20) -> None:
    """Slowly dim lights to get attention without being jarring. Restores original state."""
    saved = await _save_states(lights)
    try:
        if not saved:
            return
        start_brightness = saved[0].brightness
        for i in range(steps + 1):
            t = i / steps
            b = int(start_brightness + (target - start_brightness) * t)
            await _set_all(lights, LightState(on=True, brightness=max(3, b), temperature=saved[0].temperature))
            await asyncio.sleep(0.1)
        await asyncio.sleep(2.0)
    finally:
        await _restore_states(lights, saved)


async def set_mood(lights: list[KeyLight], mood: str) -> None:
    """Set a mood lighting preset. Does NOT restore — this is meant to persist."""
    moods = {
        "cozy": LightState(on=True, brightness=25, temperature=320),
        "focus": LightState(on=True, brightness=70, temperature=200),
        "relax": LightState(on=True, brightness=30, temperature=280),
        "energize": LightState(on=True, brightness=90, temperature=160),
        "movie": LightState(on=True, brightness=10, temperature=300),
    }
    state = moods.get(mood)
    if state is None:
        raise ValueError(f"Unknown mood: {mood!r}. Available: {', '.join(moods)}")
    await _set_all(lights, state)


def list_moods() -> list[str]:
    """List available mood names."""
    return ["cozy", "focus", "relax", "energize", "movie"]


async def _save_states(lights: list[KeyLight]) -> list[LightState]:
    return [await l.get_state() for l in lights]


async def _restore_states(lights: list[KeyLight], states: list[LightState]) -> None:
    for light, state in zip(lights, states):
        await light.set_state(state)


async def _set_all(lights: list[KeyLight], state: LightState) -> None:
    await asyncio.gather(*(l.set_state(state) for l in lights))
