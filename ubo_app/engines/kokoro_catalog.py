"""Curated catalog of Kokoro TTS voices grouped by language.

Kokoro ships ALL voices in a single bundled file pair
(``kokoro-v1.0.onnx`` + ``voices-v1.0.bin``) downloaded once from the
``kokoro-onnx`` GitHub release. The bin file contains every voice keyed
by its id (e.g. ``af_heart``, ``jf_alpha``), so a "voice switch" is just
a settings update — no per-voice file work is needed once the bundle is
on disk.

The voice id convention from
https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md is
``{lang}{gender}_{name}`` where:

* lang: ``a`` American English, ``b`` British English, ``e`` Spanish,
  ``f`` French, ``h`` Hindi, ``i`` Italian, ``j`` Japanese, ``p``
  Portuguese, ``z`` Mandarin Chinese.
* gender: ``f`` Female, ``m`` Male.

English voices are always available regardless of the system language
(set under Settings > Localization). Voices for non-English languages
only appear when the matching :class:`LanguageCode` is selected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ubo_app.constants import DATA_PATH
from ubo_app.store.services.localization import LanguageCode

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class KokoroVoiceEntry:
    """A single Kokoro voice keyed inside the bundled ``voices-v1.0.bin``."""

    id: str
    """Voice id used by kokoro-onnx, e.g. ``af_heart`` or ``jf_alpha``."""

    speaker: str
    """Human-readable speaker name (last segment of ``id``)."""

    gender: str
    """Gender code (``f`` or ``m``)."""

    locale: str
    """Locale label shown to the user, e.g. ``en_US`` or ``ja``."""


@dataclass(frozen=True)
class KokoroLanguage:
    """A grouping of Kokoro voices by top-level language code."""

    code: LanguageCode
    label: str
    voices: tuple[KokoroVoiceEntry, ...]


KOKORO_LANGUAGES: tuple[KokoroLanguage, ...] = (
    KokoroLanguage(
        code=LanguageCode.EN,
        label='English',
        voices=(
            KokoroVoiceEntry(
                id='af_heart',
                speaker='heart',
                gender='f',
                locale='en_US',
            ),
            KokoroVoiceEntry(
                id='af_bella',
                speaker='bella',
                gender='f',
                locale='en_US',
            ),
            KokoroVoiceEntry(
                id='af_nicole',
                speaker='nicole',
                gender='f',
                locale='en_US',
            ),
            KokoroVoiceEntry(
                id='am_michael',
                speaker='michael',
                gender='m',
                locale='en_US',
            ),
            KokoroVoiceEntry(
                id='am_fenrir',
                speaker='fenrir',
                gender='m',
                locale='en_US',
            ),
            KokoroVoiceEntry(
                id='bf_emma',
                speaker='emma',
                gender='f',
                locale='en_GB',
            ),
            KokoroVoiceEntry(
                id='bm_fable',
                speaker='fable',
                gender='m',
                locale='en_GB',
            ),
            KokoroVoiceEntry(
                id='bm_george',
                speaker='george',
                gender='m',
                locale='en_GB',
            ),
        ),
    ),
    KokoroLanguage(
        code=LanguageCode.ES,
        label='Spanish',
        voices=(
            KokoroVoiceEntry(
                id='ef_dora',
                speaker='dora',
                gender='f',
                locale='es',
            ),
            KokoroVoiceEntry(
                id='em_alex',
                speaker='alex',
                gender='m',
                locale='es',
            ),
        ),
    ),
    KokoroLanguage(
        code=LanguageCode.FR,
        label='French',
        voices=(
            KokoroVoiceEntry(
                id='ff_siwis',
                speaker='siwis',
                gender='f',
                locale='fr',
            ),
        ),
    ),
    KokoroLanguage(
        code=LanguageCode.IT,
        label='Italian',
        voices=(
            KokoroVoiceEntry(
                id='if_sara',
                speaker='sara',
                gender='f',
                locale='it',
            ),
            KokoroVoiceEntry(
                id='im_nicola',
                speaker='nicola',
                gender='m',
                locale='it',
            ),
        ),
    ),
    KokoroLanguage(
        code=LanguageCode.PT,
        label='Portuguese',
        voices=(
            KokoroVoiceEntry(
                id='pf_dora',
                speaker='dora',
                gender='f',
                locale='pt_BR',
            ),
            KokoroVoiceEntry(
                id='pm_alex',
                speaker='alex',
                gender='m',
                locale='pt_BR',
            ),
        ),
    ),
    KokoroLanguage(
        code=LanguageCode.ZH,
        label='Chinese',
        voices=(
            KokoroVoiceEntry(
                id='zf_xiaoxiao',
                speaker='xiaoxiao',
                gender='f',
                locale='zh',
            ),
            KokoroVoiceEntry(
                id='zm_yunxi',
                speaker='yunxi',
                gender='m',
                locale='zh',
            ),
        ),
    ),
)


KOKORO_GITHUB_RELEASE = (
    'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'
)
"""Base URL hosting the bundled Kokoro model + voices files.

The ``kokoro-onnx`` project publishes its model + voices binary as a
GitHub release asset; pipecat's ``KokoroTTSService`` auto-downloads from
the same URL when ``model_path``/``voices_path`` are not set. We pass
explicit paths so we control storage and progress UI."""

KOKORO_MODEL_FILENAME = 'kokoro-v1.0.onnx'
KOKORO_VOICES_FILENAME = 'voices-v1.0.bin'

KOKORO_DIR = DATA_PATH / 'kokoro'

DEFAULT_KOKORO_VOICE_ID = 'af_heart'


def model_path() -> Path:
    """Return the on-disk path for ``kokoro-v1.0.onnx``."""
    return KOKORO_DIR / KOKORO_MODEL_FILENAME


def voices_bin_path() -> Path:
    """Return the on-disk path for ``voices-v1.0.bin``."""
    return KOKORO_DIR / KOKORO_VOICES_FILENAME


def model_url() -> str:
    """Return the GitHub-release download URL for the Kokoro ONNX model."""
    return f'{KOKORO_GITHUB_RELEASE}/{KOKORO_MODEL_FILENAME}'


def voices_bin_url() -> str:
    """Return the GitHub-release download URL for the Kokoro voices bin."""
    return f'{KOKORO_GITHUB_RELEASE}/{KOKORO_VOICES_FILENAME}'


def all_voices() -> tuple[KokoroVoiceEntry, ...]:
    """Return every voice in the curated catalog as a flat tuple."""
    return tuple(voice for language in KOKORO_LANGUAGES for voice in language.voices)


def language_for(voice_id: str) -> KokoroLanguage | None:
    """Return the catalog language owning *voice_id*, if any."""
    for language in KOKORO_LANGUAGES:
        if any(voice.id == voice_id for voice in language.voices):
            return language
    return None


def language_by_code(code: LanguageCode) -> KokoroLanguage | None:
    """Return the catalog language matching *code*, if any."""
    for language in KOKORO_LANGUAGES:
        if language.code == code:
            return language
    return None


def voice_for(voice_id: str) -> KokoroVoiceEntry | None:
    """Return the catalog entry for *voice_id*, if any."""
    for language in KOKORO_LANGUAGES:
        for voice in language.voices:
            if voice.id == voice_id:
                return voice
    return None


def voice_label(voice: KokoroVoiceEntry) -> str:
    """Return the user-facing label for a voice in a list menu.

    Example: ``Heart · Female (en_US)``.
    """
    speaker = voice.speaker.replace('_', ' ').title()
    gender = 'Female' if voice.gender == 'f' else 'Male'
    return f'{speaker} · {gender} ({voice.locale})'


def visible_languages(system_language: LanguageCode) -> tuple[KokoroLanguage, ...]:
    """Return the languages to show in the Kokoro language picker.

    English is always present. The system language is added when it
    differs from English and the catalog has voices for it.
    """
    languages: list[KokoroLanguage] = []
    english = language_by_code(LanguageCode.EN)
    if english is not None:
        languages.append(english)

    if system_language != LanguageCode.EN:
        extra = language_by_code(system_language)
        if extra is not None and extra not in languages:
            languages.append(extra)

    return tuple(languages)
