"""Curated catalog of Vosk speech-to-text models grouped by language.

Vosk's upstream host is https://alphacephei.com/vosk/models, but the
catalog actually downloads from the ``rhasspy/vosk-models`` mirror on
HuggingFace. Two reasons:

1. **Reliability** — HuggingFace LFS has a far better uptime / TLS-cert
   record than alphacephei.com (whose Let's Encrypt cert has lapsed
   between renewals in the past, breaking downloads device-wide).
2. **Consistency** — Piper voices already come from the Rhasspy org on
   HuggingFace (``rhasspy/piper-voices``), so all assistant model
   downloads share the same trust anchor and CDN.

Each model is distributed as a single ``.zip`` archive named after the
model id (e.g. ``vosk-model-small-en-us-0.15.zip``) which expands into a
top-level directory of the same name. On HuggingFace the file lives at
``<base>/<lang-dir>/<id>.zip``, where ``<lang-dir>`` is the catalog
language code (``en``, ``de``, ``es``, …).

The catalog enumerates only the models we expose in the Manage > Vosk
picker, kept short (small variant per language) so the on-screen list
stays scrollable and the on-disk footprint reasonable. English models
are always available regardless of the system language; models for
non-English languages only appear when the matching ``LanguageCode`` is
selected under Settings > Localization.

Only models actually present in ``rhasspy/vosk-models`` are included
here. New entries must be verified against that repo to keep
``download_url_for`` URLs valid.
"""

from __future__ import annotations

from dataclasses import dataclass

from ubo_app.constants import DATA_PATH
from ubo_app.store.services.localization import LanguageCode


@dataclass(frozen=True)
class VoskModelEntry:
    """A single Vosk model that can be downloaded and run on device."""

    id: str
    """Identifier matching the directory inside the published ``.zip``.

    Example: ``vosk-model-small-en-us-0.15``. The download URL appends
    ``.zip`` to this id.
    """

    locale: str
    """Locale label shown to the user, e.g. ``en_US`` or ``de_DE``."""

    size_bytes: int
    """Approximate on-disk size of the expanded model directory."""

    quality: str = 'small'
    """Coarse quality bucket — ``small`` (compact, ~40-80 MB) or
    ``large`` (full, hundreds of MB to several GB)."""


@dataclass(frozen=True)
class VoskLanguage:
    """A grouping of Vosk models by top-level language code."""

    code: LanguageCode
    label: str
    models: tuple[VoskModelEntry, ...]


_KB = 1024
_MB = _KB * 1024


VOSK_LANGUAGES: tuple[VoskLanguage, ...] = (
    VoskLanguage(
        code=LanguageCode.EN,
        label='English',
        models=(
            VoskModelEntry(
                id='vosk-model-small-en-us-0.15',
                locale='en_US',
                size_bytes=41 * _MB,
                quality='small',
            ),
            VoskModelEntry(
                id='vosk-model-en-us-0.22-lgraph',
                locale='en_US',
                size_bytes=131 * _MB,
                quality='lgraph',
            ),
        ),
    ),
    VoskLanguage(
        code=LanguageCode.DE,
        label='German',
        models=(
            VoskModelEntry(
                id='vosk-model-small-de-0.15',
                locale='de_DE',
                size_bytes=46 * _MB,
                quality='small',
            ),
        ),
    ),
    VoskLanguage(
        code=LanguageCode.ES,
        label='Spanish',
        models=(
            VoskModelEntry(
                id='vosk-model-small-es-0.42',
                locale='es_ES',
                size_bytes=40 * _MB,
                quality='small',
            ),
        ),
    ),
    VoskLanguage(
        code=LanguageCode.FR,
        label='French',
        models=(
            VoskModelEntry(
                id='vosk-model-small-fr-0.22',
                locale='fr_FR',
                size_bytes=42 * _MB,
                quality='small',
            ),
        ),
    ),
    VoskLanguage(
        code=LanguageCode.IT,
        label='Italian',
        models=(
            VoskModelEntry(
                id='vosk-model-small-it-0.22',
                locale='it_IT',
                size_bytes=50 * _MB,
                quality='small',
            ),
        ),
    ),
    VoskLanguage(
        code=LanguageCode.PT,
        label='Portuguese',
        models=(
            VoskModelEntry(
                id='vosk-model-small-pt-0.3',
                locale='pt_BR',
                size_bytes=33 * _MB,
                quality='small',
            ),
        ),
    ),
    VoskLanguage(
        code=LanguageCode.NL,
        label='Dutch',
        models=(
            VoskModelEntry(
                id='vosk-model-small-nl-0.22',
                locale='nl_NL',
                size_bytes=40 * _MB,
                quality='small',
            ),
            VoskModelEntry(
                id='vosk-model-nl-spraakherkenning-0.6-lgraph',
                locale='nl_NL',
                size_bytes=106 * _MB,
                quality='lgraph',
            ),
        ),
    ),
    VoskLanguage(
        code=LanguageCode.ZH,
        label='Chinese',
        models=(
            VoskModelEntry(
                id='vosk-model-small-cn-0.22',
                locale='zh_CN',
                size_bytes=44 * _MB,
                quality='small',
            ),
        ),
    ),
)


VOSK_MODELS_BASE = 'https://huggingface.co/rhasspy/vosk-models/resolve/main'
"""Base URL of the rhasspy Vosk-models mirror on HuggingFace.

Files live at ``<base>/<lang_dir>/<model_id>.zip`` where ``<lang_dir>``
is the catalog language code (``en``, ``de``, ``es``, …).
"""


DEFAULT_VOSK_MODEL_ID = 'vosk-model-small-en-us-0.15'


def all_models() -> tuple[VoskModelEntry, ...]:
    """Return every model in the catalog as a flat tuple."""
    return tuple(model for language in VOSK_LANGUAGES for model in language.models)


def language_for(model_id: str) -> VoskLanguage | None:
    """Return the catalog language owning *model_id*, if any."""
    for language in VOSK_LANGUAGES:
        if any(model.id == model_id for model in language.models):
            return language
    return None


def language_by_code(code: LanguageCode) -> VoskLanguage | None:
    """Return the catalog language matching *code*, if any."""
    for language in VOSK_LANGUAGES:
        if language.code == code:
            return language
    return None


def model_for(model_id: str) -> VoskModelEntry | None:
    """Return the catalog entry for *model_id*, if any."""
    for language in VOSK_LANGUAGES:
        for model in language.models:
            if model.id == model_id:
                return model
    return None


def model_path_for(model_id: str) -> object:
    """Return the on-disk ``Path`` for *model_id*'s expanded directory.

    The ``object`` return annotation avoids a hard ``pathlib`` import in
    modules that only need string ids.
    """
    return DATA_PATH / model_id


def download_url_for(model_id: str) -> str:
    """Return the HuggingFace download URL for *model_id*'s ``.zip``.

    Resolves the owning language from the catalog (rhasspy/vosk-models on
    HuggingFace groups files into ``en/``, ``de/``, … subdirectories).
    Returns an alphacephei.com fallback for ids not present in the
    catalog so private mirrors / future entries still produce a URL.
    """
    language = language_for(model_id)
    if language is not None:
        return f'{VOSK_MODELS_BASE}/{language.code.value}/{model_id}.zip'
    # Fallback for ids not present in our curated catalog — caller knows
    # what it's asking for, so we still produce *some* URL rather than
    # raising. alphacephei is the upstream of record.
    return f'https://alphacephei.com/vosk/models/{model_id}.zip'


def format_size(size_bytes: int) -> str:
    """Render a model size as a short human-readable label."""
    if size_bytes >= 1024 * _MB:
        return f'{size_bytes / (1024 * _MB):.1f} GB'
    return f'{size_bytes / _MB:.0f} MB'


def model_label(model: VoskModelEntry) -> str:
    """Return the user-facing label for a model in a list menu.

    Example: ``Small · 40 MB (en_US)``.
    """
    quality = model.quality.replace('_', ' ').title()
    return f'{quality} · {format_size(model.size_bytes)} ({model.locale})'


def visible_languages(system_language: LanguageCode) -> tuple[VoskLanguage, ...]:
    """Return the languages to show in the Vosk language picker.

    English is always present. The system language is added when it
    differs from English and we have models for it.
    """
    languages: list[VoskLanguage] = []
    english = language_by_code(LanguageCode.EN)
    if english is not None:
        languages.append(english)

    if system_language != LanguageCode.EN:
        extra = language_by_code(system_language)
        if extra is not None and extra not in languages:
            languages.append(extra)

    return tuple(languages)
