"""Pure helper for picking a configured local TTS engine.

Used by the screen reader's "Prefer Local" option: when enabled, the reader
should route synthesis to a locally-running TTS engine instead of the
assistant's selected default (which may be cloud-based). Engines are tried in
priority order and the first one that is set up wins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.services.assistant import AssistantTTSName

if TYPE_CHECKING:
    from collections.abc import Mapping

# Local TTS engines, highest priority first. ``provider_setup_status`` is keyed
# by each engine's ``name`` (see ubo_app/engines/piper.py, kokoro.py), which
# equals the ``AssistantTTSName`` value.
LOCAL_TTS_PROVIDERS: tuple[AssistantTTSName, ...] = (
    AssistantTTSName.PIPER,
    AssistantTTSName.KOKORO,
)


def first_configured_local_tts(
    provider_setup_status: Mapping[str, bool],
) -> AssistantTTSName | None:
    """Return the highest-priority local TTS that is set up, else ``None``.

    ``None`` means no local engine is configured; callers fall back to the
    assistant's default TTS.
    """
    return next(
        (
            provider
            for provider in LOCAL_TTS_PROVIDERS
            if provider_setup_status.get(provider.value, False)
        ),
        None,
    )


def has_any_tts_configured(provider_setup_status: Mapping[str, bool]) -> bool:
    """Return True iff at least one TTS engine (local or cloud) is set up.

    ``provider_setup_status`` reports each engine's ``is_setup`` — for cloud
    engines that means credentials are present, for local engines that the
    model/voice is downloaded — so this reflects whether the screen reader has
    anything that can actually speak.
    """
    return any(
        provider_setup_status.get(name.value, False) for name in AssistantTTSName
    )
