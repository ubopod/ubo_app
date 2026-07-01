"""Shared cloud-TTS voice helpers for the assistant subprocess.

Both TTS construction paths — the one-shot pipeline (``request_providers``) and
the live switcher (``ubo_tts``) — need to turn a selected voice id into the
provider-specific kwargs. Core's ``cloud_voice_catalog`` is intentionally not
importable from the subprocess, so this module keeps the small amount of
provider-mapping logic in one place to avoid drift between the two callers.
"""

from __future__ import annotations

import contextlib
from typing import Any

from pipecat.services.google.tts import GoogleTTSService
from pipecat.transcriptions.language import Language

# Spanish Rime voices — mirror the ``ES`` group in core's
# ``cloud_voice_catalog.RIME_LANGUAGES``. A wrong language hint would
# mispronounce a Spanish voice as English.
RIME_SPANISH_VOICES = frozenset({'diego', 'isa', 'dolores'})

_GOOGLE_LOCALE_SEGMENTS = 2


def rime_language(voice_id: str) -> Language:
    """Return the Rime ``InputParams.language`` for the selected voice."""
    return Language.ES if voice_id in RIME_SPANISH_VOICES else Language.EN


def google_voice_kwargs(voice_id: str) -> dict[str, Any]:
    """Build ``voice_id`` + ``params.language`` kwargs from a Google voice name.

    Google voice names encode their locale (``en-US-Chirp3-HD-Aoede``); derive
    the BCP-47 language from the first two segments. Falls back to ``voice_id``
    alone when the locale can't be mapped to a Pipecat ``Language``.
    """
    if not voice_id:
        return {}
    kwargs: dict[str, Any] = {'voice_id': voice_id}
    parts = voice_id.split('-')
    if len(parts) >= _GOOGLE_LOCALE_SEGMENTS:
        locale = f'{parts[0]}-{parts[1]}'
        with contextlib.suppress(ValueError):
            kwargs['params'] = GoogleTTSService.InputParams(
                language=Language(locale),
            )
    return kwargs
