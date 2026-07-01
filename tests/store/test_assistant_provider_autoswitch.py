"""Tests for the pipeline provider auto-switch fallback helpers.

When a selected STT/LLM/TTS engine becomes unconfigured (credentials deleted or
its on-disk model removed) the assistant service switches the selection to
another configured engine, local-first, via ``first_configured_engine`` /
``is_engine_configured`` (``services/090-assistant/engines_registry.py``). These
unit tests pin that selection logic against the real engine registries.

Key subtlety covered: ``provider_setup_status`` is keyed by ``engine.name``, NOT
the enum value — both Google STT variants map to ``GoogleCloudEngine`` whose
name is ``'google_cloud'`` — so the helpers must resolve through the engine
instance, never the enum value.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ubo_app.store.services.assistant import (
    AssistantLLMName,
    AssistantSTTName,
    AssistantTTSName,
)

if TYPE_CHECKING:
    from types import ModuleType

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load_registry() -> ModuleType:
    """Load ``engines_registry`` by file path (its dir isn't an import package)."""
    spec = importlib.util.spec_from_file_location(
        'assistant_engines_registry_test',
        SERVICE_PATH / 'engines_registry.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_REG = _load_registry()
STT_ENGINES = _REG.STT_ENGINES
LLM_ENGINES = _REG.LLM_ENGINES
TTS_ENGINES = _REG.TTS_ENGINES
first_configured_engine = _REG.first_configured_engine
is_engine_configured = _REG.is_engine_configured


def _name(registry: dict, key: object) -> str:
    """Return *key*'s provider_setup_status key — i.e. its engine's ``name``."""
    return registry[key].name


def test_prefers_local_over_cloud() -> None:
    """A configured local engine wins over a configured cloud engine."""
    status = {
        _name(TTS_ENGINES, AssistantTTSName.KOKORO): True,
        _name(TTS_ENGINES, AssistantTTSName.OPENAI): True,
    }
    assert (
        first_configured_engine(TTS_ENGINES, status) == AssistantTTSName.KOKORO
    )


def test_first_local_in_registry_order() -> None:
    """Among configured locals, registry order breaks the tie (Piper first)."""
    status = {
        _name(TTS_ENGINES, AssistantTTSName.PIPER): True,
        _name(TTS_ENGINES, AssistantTTSName.KOKORO): True,
    }
    assert (
        first_configured_engine(TTS_ENGINES, status) == AssistantTTSName.PIPER
    )


def test_falls_back_to_cloud_when_no_local() -> None:
    """With no local configured, the first configured cloud engine is chosen."""
    status = {_name(TTS_ENGINES, AssistantTTSName.OPENAI): True}
    assert (
        first_configured_engine(TTS_ENGINES, status) == AssistantTTSName.OPENAI
    )


def test_none_when_nothing_configured() -> None:
    """No configured engine → None (caller keeps the current selection)."""
    assert first_configured_engine(TTS_ENGINES, {}) is None


def test_google_detected_by_engine_name_not_enum_value() -> None:
    """Google STT is keyed 'google_cloud', not the 'google' enum value."""
    # Keyed by the real engine name → resolves to a Google STT variant.
    status = {_name(STT_ENGINES, AssistantSTTName.GOOGLE): True}
    result = first_configured_engine(STT_ENGINES, status)
    assert result in {AssistantSTTName.GOOGLE, AssistantSTTName.GOOGLE_SEGMENTED}
    # Keyed by the enum *value* ('google') → no engine has that name → not found.
    assert first_configured_engine(STT_ENGINES, {'google': True}) is None


def test_is_engine_configured_reflects_status() -> None:
    """is_engine_configured reads the engine's name-keyed status."""
    openai_key = _name(TTS_ENGINES, AssistantTTSName.OPENAI)
    assert not is_engine_configured(
        TTS_ENGINES,
        AssistantTTSName.OPENAI,
        {openai_key: False},
    )
    assert is_engine_configured(
        TTS_ENGINES,
        AssistantTTSName.OPENAI,
        {openai_key: True},
    )


def test_is_engine_configured_defaults_true_before_populated() -> None:
    """Absent from status (e.g. cold boot) → True, so nothing is switched."""
    assert is_engine_configured(TTS_ENGINES, AssistantTTSName.PIPER, {})


def test_llm_skips_generic_adder() -> None:
    """The generic-LLM adder is never returned as a fallback when skipped."""
    status = {
        _name(LLM_ENGINES, AssistantLLMName.OLLAMA): True,
        _name(LLM_ENGINES, AssistantLLMName.OPENAI): True,
    }
    result = first_configured_engine(
        LLM_ENGINES,
        status,
        skip=(AssistantLLMName.GENERIC,),
    )
    assert result == AssistantLLMName.OLLAMA  # local Ollama beats cloud OpenAI
    assert result != AssistantLLMName.GENERIC
