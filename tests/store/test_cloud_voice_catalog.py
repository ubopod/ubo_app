"""Tests for the cloud TTS voice catalog (language adaptation + lookups)."""

from __future__ import annotations

from ubo_app.engines import cloud_voice_catalog as catalog
from ubo_app.store.services.assistant import DEFAULT_VOICES, AssistantTTSName
from ubo_app.store.services.localization import LanguageCode


def test_visible_languages_english_only_by_default() -> None:
    """An English system shows only the English Rime grouping."""
    visible = catalog.visible_languages(catalog.RIME_LANGUAGES, LanguageCode.EN)
    assert [language.code for language in visible] == [LanguageCode.EN]


def test_visible_languages_adds_system_language() -> None:
    """A Spanish system adds the Spanish Rime grouping after English."""
    visible = catalog.visible_languages(catalog.RIME_LANGUAGES, LanguageCode.ES)
    assert [language.code for language in visible] == [
        LanguageCode.EN,
        LanguageCode.ES,
    ]


def test_visible_languages_omits_unavailable_language() -> None:
    """A language Rime has no voices for (German) is not shown."""
    visible = catalog.visible_languages(catalog.RIME_LANGUAGES, LanguageCode.DE)
    assert [language.code for language in visible] == [LanguageCode.EN]


def test_google_voice_id_encodes_locale() -> None:
    """Google voice ids carry their locale prefix for language derivation."""
    voice = catalog.voice_for(
        'en-US-Chirp3-HD-Aoede',
        languages=catalog.GOOGLE_LANGUAGES,
    )
    assert voice is not None
    assert voice.id.startswith('en-US-')


def test_google_voices_are_chirp3_hd() -> None:
    """Streaming synthesis only accepts Chirp 3: HD voices."""
    for language in catalog.GOOGLE_LANGUAGES:
        for voice in language.voices:
            assert '-Chirp3-HD-' in voice.id, voice.id


def test_deepgram_default_voice_in_english_group() -> None:
    """The Deepgram default (``aura-2-helena-en``) lives in the English group."""
    english = catalog.language_by_code(
        catalog.DEEPGRAM_LANGUAGES,
        LanguageCode.EN,
    )
    assert english is not None
    assert any(voice.id == 'aura-2-helena-en' for voice in english.voices)


def test_deepgram_voices_are_aura_ids() -> None:
    """Every Deepgram voice id is a full Aura model string."""
    for language in catalog.DEEPGRAM_LANGUAGES:
        for voice in language.voices:
            assert voice.id.startswith('aura-'), voice.id
            assert voice.id.endswith(f'-{language.code.value}'), voice.id


def test_default_cloud_voices_exist_in_catalog() -> None:
    """Every cloud provider's default voice is selectable in its catalog."""
    for tts_name, default in DEFAULT_VOICES.items():
        if not default:
            continue  # ElevenLabs has no static default (secret-backed).
        grouped = catalog.LANGUAGE_GROUPED_CATALOGS.get(tts_name, ())
        flat = catalog.FLAT_CATALOGS.get(tts_name, ())
        assert (
            catalog.voice_for(default, languages=grouped, flat=flat) is not None
        ), f'{tts_name} default {default!r} missing from catalog'


def test_venice_mirrors_kokoro_default() -> None:
    """The Venice default reuses an in-catalog Kokoro voice."""
    voice = catalog.voice_for(
        DEFAULT_VOICES[AssistantTTSName.VENICE],
        languages=catalog.VENICE_LANGUAGES,
    )
    assert voice is not None
