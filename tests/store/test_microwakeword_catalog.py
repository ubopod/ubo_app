"""Tests for the curated microWakeWord model catalog."""

from __future__ import annotations

import re

from ubo_app.engines.microwakeword_catalog import (
    MICROWAKEWORD_BASE,
    MICROWAKEWORD_COMMIT,
    MICROWAKEWORD_MODELS,
    all_models,
    download_urls_for,
    format_size,
    model_for,
    model_label,
)


def test_ids_are_unique() -> None:
    """Ids double as on-disk filenames, so a duplicate would collide on disk."""
    ids = [model.id for model in all_models()]
    assert len(ids) == len(set(ids))


def test_ids_are_filesystem_safe() -> None:
    """Ids reach ``MODELS_DIR / f'{id}.tflite'`` — keep them bare stems.

    ``delete_model`` rejects anything with a separator, so an id containing one
    would produce a model that could be downloaded but never removed.
    """
    for model in all_models():
        assert re.fullmatch(r'[a-z0-9_]+', model.id), model.id


def test_downloads_are_pinned_to_a_commit() -> None:
    """URLs must name a commit SHA, never a mutable ref like ``main``.

    A branch ref would let an upstream retrain change a model under a user
    between releases, silently altering wake-word behaviour on device.
    """
    assert re.fullmatch(r'[0-9a-f]{40}', MICROWAKEWORD_COMMIT)
    assert MICROWAKEWORD_COMMIT in MICROWAKEWORD_BASE
    assert '/main/' not in MICROWAKEWORD_BASE


def test_download_urls_pair_manifest_and_weights() -> None:
    """Each model resolves to its ``.json`` manifest plus its ``.tflite``."""
    for model in all_models():
        json_url, tflite_url = download_urls_for(model.id)
        assert json_url == f'{MICROWAKEWORD_BASE}/{model.id}.json'
        assert tflite_url == f'{MICROWAKEWORD_BASE}/{model.id}.tflite'
        assert json_url.startswith('https://')
        assert tflite_url.startswith('https://')


def test_model_for_returns_none_for_unknown_id() -> None:
    """Unknown ids resolve to None — the reducer's authorization check."""
    assert model_for('definitely_not_a_wake_word') is None
    assert model_for('') is None


def test_model_for_resolves_every_catalog_entry() -> None:
    """Every shipped entry is reachable by id."""
    for model in MICROWAKEWORD_MODELS:
        assert model_for(model.id) is model


def test_probability_cutoffs_are_in_range() -> None:
    """Cutoffs map to a trigger sensitivity of ``1 - cutoff``, so keep them 0-1."""
    for model in all_models():
        assert 0.0 < model.probability_cutoff <= 1.0, model.id


def test_stop_model_is_offered() -> None:
    """``stop`` is exposed deliberately — it backs ``WakeMode.STOP_TALKING``.

    Upstream hides it from its own picker, so this asserts our divergence is
    intentional rather than a stale copy of their list.
    """
    assert model_for('stop') is not None


def test_model_label_includes_phrase_and_size() -> None:
    """Menu rows show the wake phrase and how big the download is."""
    model = model_for('hey_jarvis')
    assert model is not None
    label = model_label(model)
    assert model.label in label
    assert format_size(model.size_bytes) in label


def test_format_size_renders_kilobytes() -> None:
    """These models are tens of KB — MB rounding would show every one as ``0 MB``."""
    assert format_size(52272) == '51 KB'
