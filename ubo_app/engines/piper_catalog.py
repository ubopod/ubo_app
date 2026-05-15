"""Curated catalog of Piper TTS voices grouped by language.

Piper publishes its voices at
https://huggingface.co/rhasspy/piper-voices/tree/main . Paths follow
``{lang}/{lang_country}/{speaker}/{quality}/{lang_country}-{speaker}-{quality}``
and each voice is split into two files: ``.onnx`` (the model) and
``.onnx.json`` (the dataset/voice config). The catalog below enumerates
the voices we expose in the Manage > Piper picker — kept small (<= 4 per
language) so the on-screen list stays scrollable.

English voices are always available regardless of the system language
(set under Settings > Localization). Voices for non-English languages
only appear when the matching ``LanguageCode`` is selected.
"""

from __future__ import annotations

from dataclasses import dataclass

from ubo_app.constants import DATA_PATH
from ubo_app.store.services.localization import LanguageCode


@dataclass(frozen=True)
class PiperVoiceEntry:
    """A single Piper voice that can be downloaded and run on device."""

    id: str
    """HuggingFace path of the voice without file extension.

    Example: ``en/en_US/kristin/medium/en_US-kristin-medium``.
    The ``.onnx`` and ``.onnx.json`` files share this prefix.
    """

    speaker: str
    quality: str
    locale: str
    """Locale label shown to the user, e.g. ``en_US`` or ``es_MX``."""

    sample_rate: int
    """Sample rate declared by the voice's JSON config. Informational
    only — the subprocess re-reads this from disk after loading the
    model."""

    size_bytes: int
    """Approximate on-disk size of the ``.onnx`` file."""

    onnx_sha256: str = ''
    """SHA256 of the ``.onnx`` file. Empty string disables hash check
    for this voice. Backfill from HuggingFace LFS pointers when
    available — without it we can still run the voice, we just can't
    detect on-disk corruption."""


@dataclass(frozen=True)
class PiperLanguage:
    """A grouping of Piper voices by top-level language code."""

    code: LanguageCode
    label: str
    voices: tuple[PiperVoiceEntry, ...]


_KB = 1024
_MB = _KB * 1024


PIPER_LANGUAGES: tuple[PiperLanguage, ...] = (
    PiperLanguage(
        code=LanguageCode.EN,
        label='English',
        voices=(
            PiperVoiceEntry(
                id='en/en_US/kristin/medium/en_US-kristin-medium',
                speaker='kristin',
                quality='medium',
                locale='en_US',
                sample_rate=22050,
                size_bytes=63 * _MB,
                onnx_sha256=(
                    '5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4'
                ),
            ),
            PiperVoiceEntry(
                id='en/en_US/amy/medium/en_US-amy-medium',
                speaker='amy',
                quality='medium',
                locale='en_US',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='en/en_US/joe/medium/en_US-joe-medium',
                speaker='joe',
                quality='medium',
                locale='en_US',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='en/en_US/lessac/high/en_US-lessac-high',
                speaker='lessac',
                quality='high',
                locale='en_US',
                sample_rate=22050,
                size_bytes=114 * _MB,
            ),
            PiperVoiceEntry(
                id='en/en_GB/alan/medium/en_GB-alan-medium',
                speaker='alan',
                quality='medium',
                locale='en_GB',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='en/en_GB/alba/medium/en_GB-alba-medium',
                speaker='alba',
                quality='medium',
                locale='en_GB',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium',
                speaker='jenny_dioco',
                quality='medium',
                locale='en_GB',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id=(
                    'en/en_GB/southern_english_female/low/'
                    'en_GB-southern_english_female-low'
                ),
                speaker='southern_english_female',
                quality='low',
                locale='en_GB',
                sample_rate=16000,
                size_bytes=21 * _MB,
            ),
        ),
    ),
    PiperLanguage(
        code=LanguageCode.DE,
        label='German',
        voices=(
            PiperVoiceEntry(
                id='de/de_DE/thorsten/medium/de_DE-thorsten-medium',
                speaker='thorsten',
                quality='medium',
                locale='de_DE',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='de/de_DE/eva_k/x_low/de_DE-eva_k-x_low',
                speaker='eva_k',
                quality='x_low',
                locale='de_DE',
                sample_rate=16000,
                size_bytes=8 * _MB,
            ),
            PiperVoiceEntry(
                id='de/de_DE/kerstin/low/de_DE-kerstin-low',
                speaker='kerstin',
                quality='low',
                locale='de_DE',
                sample_rate=16000,
                size_bytes=21 * _MB,
            ),
            PiperVoiceEntry(
                id='de/de_DE/ramona/low/de_DE-ramona-low',
                speaker='ramona',
                quality='low',
                locale='de_DE',
                sample_rate=16000,
                size_bytes=21 * _MB,
            ),
        ),
    ),
    PiperLanguage(
        code=LanguageCode.ES,
        label='Spanish',
        voices=(
            PiperVoiceEntry(
                id='es/es_ES/davefx/medium/es_ES-davefx-medium',
                speaker='davefx',
                quality='medium',
                locale='es_ES',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='es/es_ES/sharvard/medium/es_ES-sharvard-medium',
                speaker='sharvard',
                quality='medium',
                locale='es_ES',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='es/es_MX/claude/high/es_MX-claude-high',
                speaker='claude',
                quality='high',
                locale='es_MX',
                sample_rate=22050,
                size_bytes=114 * _MB,
            ),
            PiperVoiceEntry(
                id='es/es_MX/ald/medium/es_MX-ald-medium',
                speaker='ald',
                quality='medium',
                locale='es_MX',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
        ),
    ),
    PiperLanguage(
        code=LanguageCode.FR,
        label='French',
        voices=(
            PiperVoiceEntry(
                id='fr/fr_FR/siwis/medium/fr_FR-siwis-medium',
                speaker='siwis',
                quality='medium',
                locale='fr_FR',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='fr/fr_FR/gilles/low/fr_FR-gilles-low',
                speaker='gilles',
                quality='low',
                locale='fr_FR',
                sample_rate=16000,
                size_bytes=21 * _MB,
            ),
            PiperVoiceEntry(
                id='fr/fr_FR/tom/medium/fr_FR-tom-medium',
                speaker='tom',
                quality='medium',
                locale='fr_FR',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='fr/fr_FR/upmc/medium/fr_FR-upmc-medium',
                speaker='upmc',
                quality='medium',
                locale='fr_FR',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
        ),
    ),
    PiperLanguage(
        code=LanguageCode.IT,
        label='Italian',
        voices=(
            PiperVoiceEntry(
                id='it/it_IT/paola/medium/it_IT-paola-medium',
                speaker='paola',
                quality='medium',
                locale='it_IT',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='it/it_IT/riccardo/x_low/it_IT-riccardo-x_low',
                speaker='riccardo',
                quality='x_low',
                locale='it_IT',
                sample_rate=16000,
                size_bytes=8 * _MB,
            ),
        ),
    ),
    PiperLanguage(
        code=LanguageCode.PT,
        label='Portuguese',
        voices=(
            PiperVoiceEntry(
                id='pt/pt_BR/faber/medium/pt_BR-faber-medium',
                speaker='faber',
                quality='medium',
                locale='pt_BR',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='pt/pt_BR/edresson/low/pt_BR-edresson-low',
                speaker='edresson',
                quality='low',
                locale='pt_BR',
                sample_rate=16000,
                size_bytes=21 * _MB,
            ),
        ),
    ),
    PiperLanguage(
        code=LanguageCode.NL,
        label='Dutch',
        voices=(
            PiperVoiceEntry(
                id='nl/nl_NL/mls_5809/low/nl_NL-mls_5809-low',
                speaker='mls_5809',
                quality='low',
                locale='nl_NL',
                sample_rate=16000,
                size_bytes=21 * _MB,
            ),
            PiperVoiceEntry(
                id='nl/nl_BE/nathalie/medium/nl_BE-nathalie-medium',
                speaker='nathalie',
                quality='medium',
                locale='nl_BE',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='nl/nl_NL/pim/medium/nl_NL-pim-medium',
                speaker='pim',
                quality='medium',
                locale='nl_NL',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
        ),
    ),
    PiperLanguage(
        code=LanguageCode.ZH,
        label='Chinese',
        voices=(
            PiperVoiceEntry(
                id='zh/zh_CN/huayan/medium/zh_CN-huayan-medium',
                speaker='huayan',
                quality='medium',
                locale='zh_CN',
                sample_rate=22050,
                size_bytes=63 * _MB,
            ),
            PiperVoiceEntry(
                id='zh/zh_CN/huayan/x_low/zh_CN-huayan-x_low',
                speaker='huayan',
                quality='x_low',
                locale='zh_CN',
                sample_rate=16000,
                size_bytes=8 * _MB,
            ),
        ),
    ),
)


PIPER_HUGGINGFACE_BASE = (
    'https://huggingface.co/rhasspy/piper-voices/resolve/main'
)
"""Base URL for Piper voice files on HuggingFace.

The original Kristin voice was pinned at commit ``0c9c5d3`` for hash
stability; pointing at ``main`` here makes new voices available without
a redeploy. SHA256 checks (when populated in the catalog) guard against
on-disk corruption regardless of which revision we fetched.
"""

DEFAULT_PIPER_VOICE_ID = 'en/en_US/kristin/medium/en_US-kristin-medium'


def all_voices() -> tuple[PiperVoiceEntry, ...]:
    """Return every voice in the catalog as a flat tuple."""
    return tuple(voice for language in PIPER_LANGUAGES for voice in language.voices)


def language_for(voice_id: str) -> PiperLanguage | None:
    """Return the catalog language owning *voice_id*, if any."""
    for language in PIPER_LANGUAGES:
        if any(voice.id == voice_id for voice in language.voices):
            return language
    return None


def language_by_code(code: LanguageCode) -> PiperLanguage | None:
    """Return the catalog language matching *code*, if any."""
    for language in PIPER_LANGUAGES:
        if language.code == code:
            return language
    return None


def voice_for(voice_id: str) -> PiperVoiceEntry | None:
    """Return the catalog entry for *voice_id*, if any."""
    for language in PIPER_LANGUAGES:
        for voice in language.voices:
            if voice.id == voice_id:
                return voice
    return None


def model_path_for(voice_id: str) -> object:
    """Return the on-disk ``Path`` for *voice_id*'s ``.onnx`` file.

    The ``object`` return annotation is to avoid a hard ``pathlib``
    import in modules that only need string ids.
    """
    return (DATA_PATH / voice_id).with_suffix('.onnx')


def json_path_for(voice_id: str) -> object:
    """Return the on-disk ``Path`` for *voice_id*'s ``.onnx.json`` file."""
    return (DATA_PATH / voice_id).with_suffix('.onnx.json')


def model_url_for(voice_id: str) -> str:
    """Return the HuggingFace download URL for *voice_id*'s ``.onnx`` file."""
    return f'{PIPER_HUGGINGFACE_BASE}/{voice_id}.onnx'


def json_url_for(voice_id: str) -> str:
    """Return the HuggingFace download URL for *voice_id*'s JSON file."""
    return f'{PIPER_HUGGINGFACE_BASE}/{voice_id}.onnx.json'


def format_size(size_bytes: int) -> str:
    """Render a voice size as a short human-readable label."""
    return f'{size_bytes / _MB:.0f} MB'


def voice_label(voice: PiperVoiceEntry) -> str:
    """Return the user-facing label for a voice in a list menu.

    Example: ``Kristin · Medium (en_US)``.
    """
    speaker = voice.speaker.replace('_', ' ').title()
    quality = voice.quality.replace('_', ' ').title()
    return f'{speaker} · {quality} ({voice.locale})'


def visible_languages(system_language: LanguageCode) -> tuple[PiperLanguage, ...]:
    """Return the languages to show in the Piper language picker.

    English is always present. The system language is added when it
    differs from English and we have voices for it.
    """
    languages: list[PiperLanguage] = []
    english = language_by_code(LanguageCode.EN)
    if english is not None:
        languages.append(english)

    if system_language != LanguageCode.EN:
        extra = language_by_code(system_language)
        if extra is not None and extra not in languages:
            languages.append(extra)

    return tuple(languages)
