"""Curated catalog of Moonshine speech-to-text models.

Moonshine runs locally on the CPU via ONNX Runtime through pipecat's
``MoonshineSTTService`` (backed by the ``moonshine_voice`` package). Unlike
Vosk — where the *core* process downloads a ``.zip`` to ``DATA_PATH`` — the
Moonshine model is downloaded and cached by the ``moonshine_voice`` library
*inside the assistant subprocess* on first use (into ``moonshine_voice``'s
local model cache under the user cache dir).
This catalog therefore only enumerates the variants we expose in the
Manage > Moonshine picker; it carries no download URLs or on-disk paths.

The ``id`` of each entry is the pipecat ``Model`` enum string accepted by
``MoonshineSTTService.Settings(model=...)``. Moonshine is English-only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MoonshineModelEntry:
    """A single Moonshine model that can be downloaded and run on device."""

    id: str
    """pipecat ``Model`` enum string, e.g. ``tiny`` or ``small-streaming``."""

    label: str
    """User-facing label shown in the model picker, e.g. ``Tiny``."""

    streaming: bool
    """Whether this is a streaming-architecture variant (lower latency)."""

    size_label: str
    """Coarse human-readable size hint, e.g. ``~27 MB``."""


# Default is the smallest model — fast, low-footprint, downloads quickly.
DEFAULT_MOONSHINE_MODEL_ID = 'tiny'


MOONSHINE_MODELS: tuple[MoonshineModelEntry, ...] = (
    MoonshineModelEntry(
        id='tiny',
        label='Tiny',
        streaming=False,
        size_label='~27 MB',
    ),
    MoonshineModelEntry(
        id='base',
        label='Base',
        streaming=False,
        size_label='~60 MB',
    ),
    MoonshineModelEntry(
        id='tiny-streaming',
        label='Tiny (streaming)',
        streaming=True,
        size_label='~27 MB',
    ),
    MoonshineModelEntry(
        id='small-streaming',
        label='Small (streaming)',
        streaming=True,
        size_label='~190 MB',
    ),
    MoonshineModelEntry(
        id='medium-streaming',
        label='Medium (streaming)',
        streaming=True,
        size_label='~410 MB',
    ),
)


def all_models() -> tuple[MoonshineModelEntry, ...]:
    """Return every model in the catalog as a flat tuple."""
    return MOONSHINE_MODELS


def model_for(model_id: str) -> MoonshineModelEntry | None:
    """Return the catalog entry for *model_id*, if any."""
    return next((model for model in MOONSHINE_MODELS if model.id == model_id), None)


def model_label(model: MoonshineModelEntry) -> str:
    """Return the user-facing label for a model in a list menu.

    Example: ``Tiny · ~27 MB``.
    """
    return f'{model.label} · {model.size_label}'
