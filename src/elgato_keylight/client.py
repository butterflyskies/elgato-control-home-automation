"""Async HTTP client for Elgato Key Light API."""

from __future__ import annotations

import httpx

from elgato_keylight.models import DeviceInfo, LightConfig, LightState


class KeyLight:
    """Async client for a single Elgato Key Light."""

    def __init__(self, config: LightConfig, timeout: float = 5.0):
        self.config = config
        self.name = config.name
        self.device_id = config.id
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=timeout,
        )

    async def __aenter__(self) -> KeyLight:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def get_state(self) -> LightState:
        """Get current light state."""
        resp = await self._client.get("/elgato/lights")
        resp.raise_for_status()
        data = resp.json()
        return LightState.from_api(data["lights"][0])

    async def set_state(self, state: LightState) -> LightState:
        """Set light state, returns the new state."""
        payload = {"numberOfLights": 1, "lights": [state.to_api()]}
        resp = await self._client.put("/elgato/lights", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return LightState.from_api(data["lights"][0])

    async def turn_on(self, brightness: int | None = None, temperature: int | None = None) -> LightState:
        """Turn the light on, optionally setting brightness and temperature."""
        state = await self.get_state()
        state.on = True
        if brightness is not None:
            state.brightness = brightness
        if temperature is not None:
            state.temperature = temperature
        return await self.set_state(state)

    async def turn_off(self) -> LightState:
        """Turn the light off."""
        state = await self.get_state()
        state.on = False
        return await self.set_state(state)

    async def toggle(self) -> LightState:
        """Toggle the light on/off."""
        state = await self.get_state()
        state.on = not state.on
        return await self.set_state(state)

    async def set_brightness(self, brightness: int) -> LightState:
        """Set brightness (0-100)."""
        brightness = max(0, min(100, brightness))
        state = await self.get_state()
        state.brightness = brightness
        return await self.set_state(state)

    async def adjust_brightness(self, delta: int) -> LightState:
        """Adjust brightness by delta (positive = brighter, negative = dimmer)."""
        state = await self.get_state()
        state.brightness = max(0, min(100, state.brightness + delta))
        return await self.set_state(state)

    async def set_temperature(self, temperature: int) -> LightState:
        """Set color temperature (143-344 in Elgato units)."""
        temperature = max(143, min(344, temperature))
        state = await self.get_state()
        state.temperature = temperature
        return await self.set_state(state)

    async def identify(self) -> None:
        """Flash the light briefly to identify it."""
        resp = await self._client.post("/elgato/lights/identify")
        resp.raise_for_status()

    async def get_info(self) -> DeviceInfo:
        """Get device information."""
        resp = await self._client.get("/elgato/accessory-info")
        resp.raise_for_status()
        return DeviceInfo.from_api(resp.json())
