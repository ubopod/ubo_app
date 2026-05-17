"""Tests for the curated Vosk STT model catalog and selector helpers."""

from __future__ import annotations

from ubo_app.engines.vosk_catalog import (
    DEFAULT_VOSK_MODEL_ID,
    VOSK_LANGUAGES,
    all_models,
    download_url_for,
    language_by_code,
    language_for,
    model_for,
    model_label,
    model_path_for,
    visible_languages,
)
from ubo_app.store.services.localization import LanguageCode


def test_default_model_resolvable() -> None:
    """The catalog must know about the default English small model."""
    entry = model_for(DEFAULT_VOSK_MODEL_ID)
    assert entry is not None
    assert entry.locale == 'en_US'
    assert entry.quality == 'small'

    language = language_for(DEFAULT_VOSK_MODEL_ID)
    assert language is not None
    assert language.code == LanguageCode.EN


def test_path_helper_uses_model_id_as_directory() -> None:
    """``model_path_for`` derives the on-disk directory from the model id."""
    path = str(model_path_for(DEFAULT_VOSK_MODEL_ID))
    assert path.endswith(DEFAULT_VOSK_MODEL_ID)


def test_url_helper_targets_huggingface_mirror() -> None:
    """Download URLs point at the rhasspy/vosk-models mirror on HuggingFace.

    HuggingFace is far more reliable than alphacephei.com (whose Let's
    Encrypt cert has historically lapsed mid-renewal), and is already the
    host we depend on for Piper voices, so STT and TTS share trust.
    """
    url = download_url_for(DEFAULT_VOSK_MODEL_ID)
    assert url.startswith('https://huggingface.co/rhasspy/vosk-models/')
    assert url.endswith(f'/en/{DEFAULT_VOSK_MODEL_ID}.zip')


def test_url_helper_uses_catalog_language_subdir() -> None:
    """Each model's URL nests under its owning language code on the mirror."""
    for language in VOSK_LANGUAGES:
        for model in language.models:
            url = download_url_for(model.id)
            assert f'/{language.code.value}/{model.id}.zip' in url, model.id


def test_url_helper_falls_back_for_unknown_model() -> None:
    """Ids outside the curated catalog still resolve to *some* URL."""
    url = download_url_for('vosk-model-unknown-xx-9.9')
    assert url.endswith('vosk-model-unknown-xx-9.9.zip')


def test_all_languages_have_at_least_one_model() -> None:
    """Empty languages would create dead-end menu rows; the picker must not."""
    for language in VOSK_LANGUAGES:
        assert language.models, language.code


def test_model_ids_are_unique() -> None:
    """Model ids must be unique across the catalog so lookups are unambiguous."""
    ids = [model.id for model in all_models()]
    assert len(ids) == len(set(ids))


def test_visible_languages_always_includes_english() -> None:
    """English models are always available, regardless of system language."""
    for code in LanguageCode:
        languages = visible_languages(code)
        assert any(lang.code == LanguageCode.EN for lang in languages), code


def test_visible_languages_adds_system_language() -> None:
    """Setting system language to Spanish surfaces Spanish models."""
    languages = visible_languages(LanguageCode.ES)
    codes = {lang.code for lang in languages}
    assert codes == {LanguageCode.EN, LanguageCode.ES}


def test_visible_languages_english_only_when_system_is_english() -> None:
    """When system language is English, no extra languages are added."""
    languages = visible_languages(LanguageCode.EN)
    codes = {lang.code for lang in languages}
    assert codes == {LanguageCode.EN}


def test_language_by_code_round_trip() -> None:
    """Every catalog language is reachable via ``language_by_code``."""
    for language in VOSK_LANGUAGES:
        assert language_by_code(language.code) is language


def test_model_label_includes_quality_and_locale() -> None:
    """Model labels render quality and locale so users can tell variants apart."""
    entry = model_for(DEFAULT_VOSK_MODEL_ID)
    assert entry is not None
    label = model_label(entry)
    assert 'Small' in label
    assert 'en_US' in label
