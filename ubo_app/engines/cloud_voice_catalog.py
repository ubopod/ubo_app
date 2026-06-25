"""Curated voice catalogs for the cloud TTS providers.

Local engines (Piper/Kokoro) keep their own ``*_catalog`` modules with
download bookkeeping; cloud voices are remote, so this module only needs the
``(id, label)`` pairs the picker shows.

Two shapes, mirroring how the providers actually behave:

* **Language-grouped** (Rime, Google, Venice) — voices are tied to a language,
  so the picker adapts to the selected system language exactly like Piper /
  Kokoro: English is always shown, the system language is added when the
  catalog has voices for it (see :func:`visible_languages`).
* **Flat** (OpenAI) — voices are multilingual (one voice speaks any language),
  so there is nothing to filter by language.

ElevenLabs is intentionally absent: its voices are user-supplied ids plus a
list fetched live from ``GET /v2/voices`` — there is no static catalog.
"""

from __future__ import annotations

from dataclasses import dataclass

from ubo_app.engines.kokoro_catalog import KOKORO_LANGUAGES
from ubo_app.store.services.assistant import AssistantTTSName
from ubo_app.store.services.localization import LanguageCode


@dataclass(frozen=True)
class CloudVoiceEntry:
    """A single selectable cloud TTS voice.

    ``id`` is the opaque string passed to the provider (OpenAI ``voice``, Rime
    ``voice_id``, Google ``voice_name``, Venice ``voice``); ``label`` is the
    display name.
    """

    id: str
    label: str


@dataclass(frozen=True)
class CloudVoiceLanguage:
    """A grouping of cloud voices by top-level language code."""

    code: LanguageCode
    label: str
    voices: tuple[CloudVoiceEntry, ...]


# --- OpenAI: flat, multilingual --------------------------------------------
# The 9 voices supported across every OpenAI TTS model (``tts-1`` /
# ``tts-1-hd`` / ``gpt-4o-mini-tts``). The 4 newer voices (ballad/verse/marin/
# cedar) require ``gpt-4o-mini-tts`` and are omitted to stay model-agnostic.
OPENAI_VOICES: tuple[CloudVoiceEntry, ...] = tuple(
    CloudVoiceEntry(id=voice_id, label=voice_id.title())
    for voice_id in (
        'alloy',
        'ash',
        'coral',
        'echo',
        'fable',
        'nova',
        'onyx',
        'sage',
        'shimmer',
    )
)


# --- Rime: language-grouped ------------------------------------------------
# Curated ``mistv2`` speakers. ``mistv2`` has rich English coverage and a
# handful of Spanish voices; broader language coverage lives on Rime's
# ``arcana`` model and is intentionally out of scope here, so only the
# well-attested English + Spanish voices are exposed.
RIME_LANGUAGES: tuple[CloudVoiceLanguage, ...] = (
    CloudVoiceLanguage(
        code=LanguageCode.EN,
        label='English',
        voices=(
            CloudVoiceEntry(id='antoine', label='Antoine'),
            CloudVoiceEntry(id='abbie', label='Abbie'),
            CloudVoiceEntry(id='allison', label='Allison'),
            CloudVoiceEntry(id='ally', label='Ally'),
            CloudVoiceEntry(id='bayou', label='Bayou'),
        ),
    ),
    CloudVoiceLanguage(
        code=LanguageCode.ES,
        label='Spanish',
        voices=(
            CloudVoiceEntry(id='diego', label='Diego'),
            CloudVoiceEntry(id='isa', label='Isa'),
            CloudVoiceEntry(id='dolores', label='Dolores'),
        ),
    ),
)


# --- Google: language-grouped ----------------------------------------------
# Google Cloud TTS voice names encode their locale (``en-US-Chirp3-HD-Aoede``);
# the subprocess derives ``params.language`` from the name prefix. Pipecat's
# ``GoogleTTSService`` uses *streaming* synthesis, which only accepts
# **Chirp 3: HD** voices, so the curated set uses those (star/deity names,
# available across the supported locales). Neural2/Wavenet voices would fail
# with "only Chirp 3: HD voices are supported for streaming synthesis".
def _google_language(
    code: LanguageCode,
    label: str,
    locale: str,
    names: tuple[str, ...],
) -> CloudVoiceLanguage:
    return CloudVoiceLanguage(
        code=code,
        label=label,
        voices=tuple(
            CloudVoiceEntry(id=f'{locale}-Chirp3-HD-{name}', label=name)
            for name in names
        ),
    )


GOOGLE_LANGUAGES: tuple[CloudVoiceLanguage, ...] = (
    _google_language(
        LanguageCode.EN,
        'English',
        'en-US',
        ('Aoede', 'Charon', 'Kore', 'Puck'),
    ),
    _google_language(
        LanguageCode.DE,
        'German',
        'de-DE',
        ('Aoede', 'Charon', 'Kore'),
    ),
    _google_language(
        LanguageCode.ES,
        'Spanish',
        'es-ES',
        ('Aoede', 'Charon', 'Kore'),
    ),
    _google_language(
        LanguageCode.FR,
        'French',
        'fr-FR',
        ('Aoede', 'Charon', 'Kore'),
    ),
    _google_language(
        LanguageCode.IT,
        'Italian',
        'it-IT',
        ('Aoede', 'Charon', 'Kore'),
    ),
    _google_language(
        LanguageCode.PT,
        'Portuguese',
        'pt-BR',
        ('Aoede', 'Charon', 'Kore'),
    ),
    _google_language(
        LanguageCode.NL,
        'Dutch',
        'nl-NL',
        ('Aoede', 'Charon', 'Kore'),
    ),
    _google_language(
        LanguageCode.ZH,
        'Chinese',
        'cmn-CN',
        ('Aoede', 'Charon', 'Kore'),
    ),
)


def _venice_languages() -> tuple[CloudVoiceLanguage, ...]:
    """Venice serves Kokoro voices, so mirror the Kokoro language grouping."""
    return tuple(
        CloudVoiceLanguage(
            code=language.code,
            label=language.label,
            voices=tuple(
                CloudVoiceEntry(id=voice.id, label=voice.speaker.title())
                for voice in language.voices
            ),
        )
        for language in KOKORO_LANGUAGES
    )


VENICE_LANGUAGES: tuple[CloudVoiceLanguage, ...] = _venice_languages()


# Provider → its language-grouped catalog. Providers absent here either use a
# flat catalog (OpenAI) or have no static catalog (ElevenLabs).
LANGUAGE_GROUPED_CATALOGS: dict[
    AssistantTTSName,
    tuple[CloudVoiceLanguage, ...],
] = {
    AssistantTTSName.RIME: RIME_LANGUAGES,
    AssistantTTSName.GOOGLE: GOOGLE_LANGUAGES,
    AssistantTTSName.VENICE: VENICE_LANGUAGES,
}

# Provider → its flat (multilingual) voice list.
FLAT_CATALOGS: dict[AssistantTTSName, tuple[CloudVoiceEntry, ...]] = {
    AssistantTTSName.OPENAI: OPENAI_VOICES,
}


def all_voices(
    languages: tuple[CloudVoiceLanguage, ...],
) -> tuple[CloudVoiceEntry, ...]:
    """Flatten every voice across the given languages."""
    return tuple(voice for language in languages for voice in language.voices)


def language_by_code(
    languages: tuple[CloudVoiceLanguage, ...],
    code: LanguageCode,
) -> CloudVoiceLanguage | None:
    """Return the language grouping matching *code*, if any."""
    for language in languages:
        if language.code == code:
            return language
    return None


def language_for(
    languages: tuple[CloudVoiceLanguage, ...],
    voice_id: str,
) -> CloudVoiceLanguage | None:
    """Return the language grouping owning *voice_id*, if any."""
    for language in languages:
        if any(voice.id == voice_id for voice in language.voices):
            return language
    return None


def voice_for(
    voice_id: str,
    *,
    languages: tuple[CloudVoiceLanguage, ...] = (),
    flat: tuple[CloudVoiceEntry, ...] = (),
) -> CloudVoiceEntry | None:
    """Return the catalog entry for *voice_id* across grouped + flat voices."""
    for voice in (*all_voices(languages), *flat):
        if voice.id == voice_id:
            return voice
    return None


def visible_languages(
    languages: tuple[CloudVoiceLanguage, ...],
    system_language: LanguageCode,
) -> tuple[CloudVoiceLanguage, ...]:
    """Return the languages to show in the picker for *system_language*.

    English is always present; the system language is added when it differs
    from English and the catalog has voices for it. Mirrors
    ``piper_catalog.visible_languages`` / ``kokoro_catalog.visible_languages``.
    """
    visible: list[CloudVoiceLanguage] = []
    english = language_by_code(languages, LanguageCode.EN)
    if english is not None:
        visible.append(english)

    if system_language != LanguageCode.EN:
        extra = language_by_code(languages, system_language)
        if extra is not None and extra not in visible:
            visible.append(extra)

    return tuple(visible)
