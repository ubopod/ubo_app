"""Curated catalog of on-device Ollama models grouped by family."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OllamaModelEntry:
    """A single Ollama model that can be downloaded and run on device."""

    id: str
    label: str
    size_bytes: int
    context_window: int
    supports_thinking_hint: bool = False


@dataclass(frozen=True)
class OllamaCategory:
    """A grouping of Ollama models by family (e.g. Qwen3, Liquid AI, Gemma 3n)."""

    id: str
    label: str
    models: tuple[OllamaModelEntry, ...]


_KB = 1024
_MB = _KB * 1024
_GB = _MB * 1024


OLLAMA_CATALOG: tuple[OllamaCategory, ...] = (
    OllamaCategory(
        id='qwen3',
        label='Qwen3',
        models=(
            OllamaModelEntry(
                id='qwen3:0.6b',
                label='0.6b',
                size_bytes=523 * _MB,
                context_window=40_000,
                supports_thinking_hint=True,
            ),
            OllamaModelEntry(
                id='qwen3:1.7b',
                label='1.7b',
                size_bytes=1_400 * _MB,
                context_window=40_000,
                supports_thinking_hint=True,
            ),
            OllamaModelEntry(
                id='qwen3:4b',
                label='4b',
                size_bytes=2_500 * _MB,
                context_window=256_000,
                supports_thinking_hint=True,
            ),
            OllamaModelEntry(
                id='qwen3:8b',
                label='8b',
                size_bytes=5_200 * _MB,
                context_window=40_000,
                supports_thinking_hint=True,
            ),
            OllamaModelEntry(
                id='qwen3:14b',
                label='14b',
                size_bytes=9_300 * _MB,
                context_window=40_000,
                supports_thinking_hint=True,
            ),
        ),
    ),
    OllamaCategory(
        id='liquid_ai',
        label='Liquid AI',
        models=(
            OllamaModelEntry(
                id='liquidai/lfm2.5-350m',
                label='lfm2.5-350m',
                size_bytes=379 * _MB,
                context_window=125_000,
            ),
            OllamaModelEntry(
                id='liquidai/lfm2.5-1.2b-instruct',
                label='lfm2.5-1.2b',
                size_bytes=731 * _MB,
                context_window=125_000,
            ),
        ),
    ),
    OllamaCategory(
        id='gemma3n',
        label='Gemma 3n',
        models=(
            OllamaModelEntry(
                id='gemma3n:e2b',
                label='e2b',
                size_bytes=5_600 * _MB,
                context_window=32_000,
            ),
            OllamaModelEntry(
                id='gemma3n:e4b',
                label='e4b',
                size_bytes=7_500 * _MB,
                context_window=32_000,
            ),
        ),
    ),
)


# RAM headroom reserved for OS + Ubo App + Pipecat. Anything left over is
# considered usable for the model.
RAM_HEADROOM_BYTES = 1_500 * _MB

# Models are usually quantized; runtime memory tends to track disk size with
# a small inflation factor.
RAM_INFLATION_FACTOR = 1.2


def required_ram_bytes(entry: OllamaModelEntry) -> int:
    """Return the rough runtime RAM requirement for *entry* on a Pi."""
    return int(entry.size_bytes * RAM_INFLATION_FACTOR)


def fits_in_ram(entry: OllamaModelEntry, total_ram_bytes: int) -> bool:
    """Return True iff *entry* fits in the device's effective RAM."""
    effective = max(0, total_ram_bytes - RAM_HEADROOM_BYTES)
    return required_ram_bytes(entry) <= effective


def category_of(model_id: str) -> OllamaCategory | None:
    """Return the catalog category that owns *model_id*, if any."""
    for category in OLLAMA_CATALOG:
        if any(entry.id == model_id for entry in category.models):
            return category
    return None


def entry_for(model_id: str) -> OllamaModelEntry | None:
    """Return the catalog entry for *model_id*, if any."""
    for category in OLLAMA_CATALOG:
        for entry in category.models:
            if entry.id == model_id:
                return entry
    return None


def format_size(size_bytes: int) -> str:
    """Render a model size as a short human-readable label."""
    if size_bytes >= _GB:
        return f'{size_bytes / _GB:.1f} GB'
    return f'{size_bytes / _MB:.0f} MB'


def normalize_model_tag(tag: str) -> str:
    """Return *tag* in the canonical form Ollama uses on disk.

    Ollama is case-insensitive on the pull side but preserves casing on
    disk, and defaults the tag to ``:latest`` when none is given. So a
    catalog entry like ``liquidai/lfm2.5-350m`` lands as
    ``liquidAI/lfm2.5-350m:latest`` after ``ollama pull``. Comparing the
    catalog string verbatim to ``ollama.list()`` output therefore fails
    even though the model is downloaded and usable. Normalise both sides
    by case-folding and ensuring an explicit tag.
    """
    folded = tag.casefold()
    if ':' not in folded:
        folded = f'{folded}:latest'
    return folded
