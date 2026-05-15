# ruff: noqa: D100, D101
from __future__ import annotations

from dataclasses import field
from enum import StrEnum

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class LanguageCode(StrEnum):
    """Top-level language families supported by the device.

    Only families with at least one curated Piper voice appear here.
    Sub-locales (e.g. ``en_US`` vs ``en_GB``) are represented at the
    voice level inside ``piper_catalog`` rather than as separate enum
    members — the localization layer cares about language, not accent.
    """

    EN = 'en'
    DE = 'de'
    ES = 'es'
    FR = 'fr'
    IT = 'it'
    PT = 'pt'
    NL = 'nl'
    ZH = 'zh'


_LANGUAGE_LABELS: dict[LanguageCode, str] = {
    LanguageCode.EN: 'English',
    LanguageCode.DE: 'German',
    LanguageCode.ES: 'Spanish',
    LanguageCode.FR: 'French',
    LanguageCode.IT: 'Italian',
    LanguageCode.PT: 'Portuguese',
    LanguageCode.NL: 'Dutch',
    LanguageCode.ZH: 'Chinese',
}


def language_label(code: LanguageCode) -> str:
    """Return the human-readable label for *code*."""
    return _LANGUAGE_LABELS.get(code, code.value)


class LocalizationAction(BaseAction): ...


class LocalizationEvent(BaseEvent): ...


class LocalizationSetLanguageAction(LocalizationAction):
    language: LanguageCode


class LocalizationLanguageChangedEvent(LocalizationEvent):
    language: LanguageCode


def _load_language(value: object) -> LanguageCode:
    if isinstance(value, LanguageCode):
        return value
    if isinstance(value, str):
        try:
            return LanguageCode(value)
        except ValueError:
            return LanguageCode.EN
    return LanguageCode.EN


class LocalizationState(Immutable):
    language: LanguageCode = field(
        default=read_from_persistent_store(
            key='localization:language',
            default=LanguageCode.EN,
            mapper=_load_language,
        ),
    )
