# ruff: noqa: D103
"""MCP server base with lifespan for resource management using HTTP transport."""

from __future__ import annotations

from fastmcp import FastMCP

from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioDevice, AudioSetVolumeAction
from ubo_app.store.services.rgb_ring import (
    RgbRingBlankAction,
    RgbRingBlinkAction,
    RgbRingFillDownfromAction,
    RgbRingFillUptoAction,
    RgbRingProgressWheelAction,
    RgbRingProgressWheelStepAction,
    RgbRingPulseAction,
    RgbRingRainbowAction,
    RgbRingSpinningWheelAction,
)

mcp = FastMCP('UBO Server')


@mcp.tool()
async def set_playback_volume(volume: float) -> None:
    """Set playback volume."""
    store.dispatch(AudioSetVolumeAction(device=AudioDevice.OUTPUT, volume=volume))


@mcp.tool()
async def rgb_ring_blank() -> None:
    store.dispatch(RgbRingBlankAction())


@mcp.tool()
async def rgb_ring_rainbow(
    wait: int | None = None,
    rounds: int | None = None,
) -> None:
    kwargs = {}
    if wait is not None:
        kwargs['wait'] = wait
    if rounds is not None:
        kwargs['rounds'] = rounds
    store.dispatch(RgbRingRainbowAction(**kwargs))


@mcp.tool()
async def rgb_ring_progress_whell_step(
    color: tuple[int, int, int] | None = None,
) -> None:
    kwargs = {}
    if color is not None:
        kwargs['color'] = color
    store.dispatch(RgbRingProgressWheelStepAction(**kwargs))


@mcp.tool()
async def rgb_ring_progress(
    color: tuple[int, int, int] | None = None,
) -> None:
    kwargs = {}
    if color is not None:
        kwargs['color'] = color
    store.dispatch(RgbRingProgressWheelStepAction(**kwargs))


@mcp.tool()
async def rgb_ring_pulse(
    color: tuple[int, int, int] | None = None,
    wait: int | None = None,
    repetitions: int | None = None,
) -> None:
    kwargs = {}
    if color is not None:
        kwargs['color'] = color
    if wait is not None:
        kwargs['wait'] = wait
    if repetitions is not None:
        kwargs['repetitions'] = repetitions
    store.dispatch(RgbRingPulseAction(**kwargs))


@mcp.tool()
async def rgb_ring_blink(
    color: tuple[int, int, int] | None = None,
    wait: int | None = None,
    repetitions: int | None = None,
) -> None:
    kwargs = {}
    if color is not None:
        kwargs['color'] = color
    if wait is not None:
        kwargs['wait'] = wait
    if repetitions is not None:
        kwargs['repetitions'] = repetitions
    store.dispatch(RgbRingBlinkAction(**kwargs))


@mcp.tool()
async def rgb_ring_spinning_wheel(
    color: tuple[int, int, int] | None = None,
    wait: int | None = None,
    length: int | None = None,
    repetitions: int | None = None,
) -> None:
    kwargs = {}
    if color is not None:
        kwargs['color'] = color
    if wait is not None:
        kwargs['wait'] = wait
    if length is not None:
        kwargs['length'] = length
    if repetitions is not None:
        kwargs['repetitions'] = repetitions
    store.dispatch(RgbRingSpinningWheelAction(**kwargs))


@mcp.tool()
async def rgb_ring_progress_wheel(
    color: tuple[int, int, int] | None = None,
    percentage: int | None = None,
) -> None:
    kwargs = {}
    if color is not None:
        kwargs['color'] = color
    if percentage is not None:
        kwargs['percentage'] = percentage
    store.dispatch(RgbRingProgressWheelAction(**kwargs))


@mcp.tool()
async def rgb_ring_fill_upto(
    color: tuple[int, int, int] | None = None,
    wait: int | None = None,
    percentage: int | None = None,
) -> None:
    kwargs = {}
    if color is not None:
        kwargs['color'] = color
    if wait is not None:
        kwargs['wait'] = wait
    if percentage is not None:
        kwargs['percentage'] = percentage
    store.dispatch(RgbRingFillUptoAction(**kwargs))


@mcp.tool()
async def rgb_ring_fill_downfrom(
    color: tuple[int, int, int] | None = None,
    wait: int | None = None,
    percentage: int | None = None,
) -> None:
    kwargs = {}
    if color is not None:
        kwargs['color'] = color
    if wait is not None:
        kwargs['wait'] = wait
    if percentage is not None:
        kwargs['percentage'] = percentage
    store.dispatch(RgbRingFillDownfromAction(**kwargs))


async def mcp_server() -> None:
    await mcp.run_async(transport='http', host='localhost', port=8765)
