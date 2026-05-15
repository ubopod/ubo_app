"""Tests for the curated Piper voice catalog and selector helpers."""

from __future__ import annotations

from ubo_app.engines.piper_catalog import (
    DEFAULT_PIPER_VOICE_ID,
    PIPER_LANGUAGES,
    all_voices,
    json_path_for,
    json_url_for,
    language_by_code,
    language_for,
    model_path_for,
    model_url_for,
    visible_languages,
    voice_for,
    voice_label,
)
from ubo_app.store.services.localization import LanguageCode


def test_default_voice_resolvable() -> None:
    """The catalog must know about the default Kristin voice."""
    entry = voice_for(DEFAULT_PIPER_VOICE_ID)
    assert entry is not None
    assert entry.speaker == 'kristin'
    assert entry.locale == 'en_US'

    language = language_for(DEFAULT_PIPER_VOICE_ID)
    assert language is not None
    assert language.code == LanguageCode.EN


def test_path_helpers_use_voice_id_as_prefix() -> None:
    """``model_path_for`` / ``json_path_for`` derive paths from the voice id."""
    voice_id = DEFAULT_PIPER_VOICE_ID
    onnx = str(model_path_for(voice_id))
    metadata = str(json_path_for(voice_id))
    assert onnx.endswith(f'{voice_id}.onnx')
    assert metadata.endswith(f'{voice_id}.onnx.json')


def test_url_helpers_target_huggingface() -> None:
    """Download URLs always point at the HuggingFace ``piper-voices`` repo."""
    onnx_url = model_url_for(DEFAULT_PIPER_VOICE_ID)
    json_url = json_url_for(DEFAULT_PIPER_VOICE_ID)
    assert onnx_url.startswith('https://huggingface.co/rhasspy/piper-voices/')
    assert onnx_url.endswith(f'{DEFAULT_PIPER_VOICE_ID}.onnx')
    assert json_url.endswith(f'{DEFAULT_PIPER_VOICE_ID}.onnx.json')


def test_all_languages_have_at_least_one_voice() -> None:
    """Empty languages would create dead-end menu rows; the picker must not."""
    for language in PIPER_LANGUAGES:
        assert language.voices, language.code


def test_no_language_has_more_than_four_voices() -> None:
    """The picker is sized for ≤ 4 voices per language."""
    for language in PIPER_LANGUAGES:
        assert len(language.voices) <= 8, (language.code, len(language.voices))


def test_voice_ids_are_unique() -> None:
    """Voice ids must be unique across the catalog so lookups are unambiguous."""
    ids = [voice.id for voice in all_voices()]
    assert len(ids) == len(set(ids))


def test_visible_languages_always_includes_english() -> None:
    """English voices are always available, regardless of system language."""
    for code in LanguageCode:
        languages = visible_languages(code)
        assert any(lang.code == LanguageCode.EN for lang in languages), code


def test_visible_languages_adds_system_language() -> None:
    """Setting system language to Spanish surfaces Spanish voices."""
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
    for language in PIPER_LANGUAGES:
        assert language_by_code(language.code) is language


def test_voice_label_includes_speaker_and_quality() -> None:
    """Voice labels render speaker and quality so users can tell variants apart."""
    entry = voice_for(DEFAULT_PIPER_VOICE_ID)
    assert entry is not None
    label = voice_label(entry)
    assert 'Kristin' in label
    assert 'Medium' in label
    assert 'en_US' in label
