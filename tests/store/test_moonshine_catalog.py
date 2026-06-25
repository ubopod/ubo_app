"""Tests for the curated Moonshine STT model catalog and helpers."""

from __future__ import annotations

from ubo_app.engines.moonshine_catalog import (
    DEFAULT_MOONSHINE_MODEL_ID,
    MOONSHINE_MODELS,
    all_models,
    model_for,
    model_label,
)


def test_default_model_is_tiny_and_in_catalog() -> None:
    """The default model is ``tiny`` and is present in the catalog."""
    assert DEFAULT_MOONSHINE_MODEL_ID == 'tiny'
    entry = model_for(DEFAULT_MOONSHINE_MODEL_ID)
    assert entry is not None
    assert entry.id == 'tiny'
    assert entry.streaming is False


def test_catalog_exposes_the_english_variants() -> None:
    """The five Moonshine variants published for English are offered.

    ``base-streaming`` is deliberately absent — moonshine_voice does not publish
    it for English, so building it would raise.
    """
    ids = {model.id for model in all_models()}
    assert ids == {
        'tiny',
        'base',
        'tiny-streaming',
        'small-streaming',
        'medium-streaming',
    }


def test_model_ids_are_unique() -> None:
    """No duplicate model ids in the catalog."""
    ids = [model.id for model in MOONSHINE_MODELS]
    assert len(ids) == len(set(ids))


def test_model_for_unknown_returns_none() -> None:
    """Unknown ids resolve to ``None`` rather than raising."""
    assert model_for('does-not-exist') is None


def test_model_label_includes_size_hint() -> None:
    """The list label combines the human label and the size hint."""
    entry = model_for('tiny')
    assert entry is not None
    label = model_label(entry)
    assert entry.label in label
    assert entry.size_label in label
