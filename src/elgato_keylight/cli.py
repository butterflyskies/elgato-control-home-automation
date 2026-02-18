"""Click CLI for Elgato Key Light control."""

from __future__ import annotations

import asyncio
import json
import sys

import click

from elgato_keylight.client import KeyLight
from elgato_keylight.config import get_lights, get_preset, list_presets
from elgato_keylight.effects import (
    alert,
    celebration,
    dim_slowly,
    flash,
    list_moods,
    pulse,
    set_mood,
)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


async def _get_clients(names: tuple[str, ...] | None = None) -> list[KeyLight]:
    """Create KeyLight clients for the requested lights."""
    configs = get_lights(list(names) if names else None)
    return [KeyLight(c) for c in configs]


async def _close_all(clients: list[KeyLight]) -> None:
    for c in clients:
        await c.close()


@click.group()
@click.option("--light", "-l", multiple=True, help="Target specific light(s) by name.")
@click.pass_context
def cli(ctx, light):
    """Control Elgato Key Lights."""
    ctx.ensure_object(dict)
    ctx.obj["lights"] = light if light else None


@cli.command()
@click.pass_context
def status(ctx):
    """Show status of all lights."""

    async def _status():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                try:
                    state = await c.get_state()
                    info = await c.get_info()
                    status = "on" if state.on else "off"
                    click.echo(
                        f"{c.name} ({info.display_name or info.product_name}): "
                        f"{status}, brightness={state.brightness}%, "
                        f"temp={state.temperature} (~{state.temperature_kelvin}K)"
                    )
                except Exception as e:
                    click.echo(f"{c.name}: error — {e}", err=True)
        finally:
            await _close_all(clients)

    _run(_status())


@cli.command()
@click.pass_context
def on(ctx):
    """Turn lights on."""

    async def _on():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                await c.turn_on()
                click.echo(f"{c.name}: on")
        finally:
            await _close_all(clients)

    _run(_on())


@cli.command()
@click.pass_context
def off(ctx):
    """Turn lights off."""

    async def _off():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                await c.turn_off()
                click.echo(f"{c.name}: off")
        finally:
            await _close_all(clients)

    _run(_off())


@cli.command()
@click.pass_context
def toggle(ctx):
    """Toggle lights on/off."""

    async def _toggle():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                state = await c.toggle()
                click.echo(f"{c.name}: {'on' if state.on else 'off'}")
        finally:
            await _close_all(clients)

    _run(_toggle())


@cli.command()
@click.argument("value", type=int)
@click.pass_context
def brightness(ctx, value):
    """Set brightness (0-100)."""

    async def _brightness():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                state = await c.set_brightness(value)
                click.echo(f"{c.name}: brightness={state.brightness}%")
        finally:
            await _close_all(clients)

    _run(_brightness())


@cli.command("brightness-up")
@click.option("--step", default=10, help="Step size (default 10).")
@click.pass_context
def brightness_up(ctx, step):
    """Increase brightness."""

    async def _up():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                state = await c.adjust_brightness(step)
                click.echo(f"{c.name}: brightness={state.brightness}%")
        finally:
            await _close_all(clients)

    _run(_up())


@cli.command("brightness-down")
@click.option("--step", default=10, help="Step size (default 10).")
@click.pass_context
def brightness_down(ctx, step):
    """Decrease brightness."""

    async def _down():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                state = await c.adjust_brightness(-step)
                click.echo(f"{c.name}: brightness={state.brightness}%")
        finally:
            await _close_all(clients)

    _run(_down())


@cli.command()
@click.argument("value", type=int)
@click.pass_context
def temperature(ctx, value):
    """Set color temperature (143=cool/7000K, 344=warm/2900K)."""

    async def _temp():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                state = await c.set_temperature(value)
                click.echo(f"{c.name}: temp={state.temperature} (~{state.temperature_kelvin}K)")
        finally:
            await _close_all(clients)

    _run(_temp())


@cli.command()
@click.pass_context
def identify(ctx):
    """Flash lights to identify them."""

    async def _identify():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                await c.identify()
                click.echo(f"{c.name}: identified")
        finally:
            await _close_all(clients)

    _run(_identify())


@cli.command()
@click.argument("name")
@click.pass_context
def preset(ctx, name):
    """Apply a named preset (bright, dim, warm, cool, video)."""
    p = get_preset(name)
    if p is None:
        available = ", ".join(list_presets().keys())
        click.echo(f"Unknown preset: {name!r}. Available: {available}", err=True)
        sys.exit(1)

    async def _preset():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            for c in clients:
                state = p.to_state(light_name=c.name, device_id=c.device_id, on=True)
                await c.set_state(state)
                click.echo(f"{c.name}: preset '{name}' applied")
        finally:
            await _close_all(clients)

    _run(_preset())


# --- Effect commands ---


@cli.command("flash")
@click.option("--times", default=3, help="Number of flashes.")
@click.pass_context
def flash_cmd(ctx, times):
    """Flash lights to get attention."""

    async def _flash():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            await flash(clients, times=times)
            click.echo("Flash complete.")
        finally:
            await _close_all(clients)

    _run(_flash())


@cli.command("pulse")
@click.option("--cycles", default=3, help="Number of pulse cycles.")
@click.pass_context
def pulse_cmd(ctx, cycles):
    """Smoothly pulse brightness up and down."""

    async def _pulse():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            await pulse(clients, cycles=cycles)
            click.echo("Pulse complete.")
        finally:
            await _close_all(clients)

    _run(_pulse())


@cli.command()
@click.pass_context
def celebrate(ctx):
    """Fun alternating color temperature dance."""

    async def _celebrate():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            await celebration(clients)
            click.echo("Celebration complete!")
        finally:
            await _close_all(clients)

    _run(_celebrate())


@cli.command("alert")
@click.option("--flashes", default=5, help="Number of alert flashes.")
@click.pass_context
def alert_cmd(ctx, flashes):
    """Urgent attention-getting flash."""

    async def _alert():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            await alert(clients, flashes=flashes)
            click.echo("Alert complete.")
        finally:
            await _close_all(clients)

    _run(_alert())


@cli.command()
@click.argument("name", type=click.Choice(list_moods()))
@click.pass_context
def mood(ctx, name):
    """Set mood lighting (cozy, focus, relax, energize, movie)."""

    async def _mood():
        clients = await _get_clients(ctx.obj["lights"])
        try:
            await set_mood(clients, name)
            click.echo(f"Mood set: {name}")
        finally:
            await _close_all(clients)

    _run(_mood())
