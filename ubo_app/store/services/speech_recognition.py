"""Definitions for speech recognition service actions, events and state."""

from __future__ import annotations

import json
import math
from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Iterable

from ubo_app.constants.assistant import (
    ASSISTANT_CONVERSATION_END_PHRASES,
    ASSISTANT_CONVERSATION_WAKE_WORD,
    ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
    ASSISTANT_STOP_TALKING_PHRASE,
    HOME_ASSISTANT_WAKE_PHRASE,
    INTENTS_WAKE_WORD,
)
from ubo_app.utils.persistent_store import read_from_persistent_store


class WakeMode(StrEnum):
    """The assistant behaviour a detected wake word triggers.

    Each wake-word :class:`WakeWordTrigger` is tagged with one of these. They
    discriminate assistant trigger policies without coupling them to the literal
    phrase text. The conversation-end phrases are deliberately *not* a ``WakeMode``
    — they are consumed assistant-side, not detected as a wake word.
    """

    INTENTS = 'intents'
    QUICK_CHAT = 'quick_chat'
    CONVERSATION = 'conversation'
    STOP_TALKING = 'stop_talking'
    # Hands the utterance to Home Assistant over the Wyoming satellite rather than
    # the on-device assistant. Deliberately outside the ``assistant_enabled`` gate:
    # it is a separate destination, not a mode of the local assistant.
    HOME_ASSISTANT = 'home_assistant'


class WakeWordEngineName(StrEnum):
    """Available wake word detection engines."""

    VOSK = 'vosk'
    OPENWAKEWORD = 'openwakeword'
    MICROWAKEWORD = 'microwakeword'
    # PICOVOICE = 'picovoice'  # noqa: ERA001  (future — see EnginesManager registry)


class WakeWordModelStatus(StrEnum):
    """Status of wake word models."""

    NOT_AVAILABLE = 'not_available'
    DOWNLOADING = 'downloading'
    AVAILABLE = 'available'
    ERROR = 'error'


class WakeWordModelStatusEntry(Immutable):
    """One engine's model availability/download status.

    A tuple of these (rather than an enum-keyed dict) backs the state so it
    round-trips through the gRPC object<->message helpers, which don't preserve
    enum map keys.
    """

    engine: WakeWordEngineName
    status: WakeWordModelStatus
    # Which model the ``DOWNLOADING`` status refers to, for engines that fetch
    # one model at a time (microWakeWord). Empty for engine-wide batch downloads
    # (OpenWakeWord) and for every non-downloading status.
    model_id: str = ''


class SpeechRecognitionAction(BaseAction):
    """Base class for speech recognition actions."""


# --- Wake engine / trigger configuration -----------------------------------


class WakeEngineSetEnabledAction(SpeechRecognitionAction):
    """Enable or disable a whole wake-word engine.

    Engines run concurrently; enabling more than one streams the same mic audio
    to each, and whichever matches one of *its* enabled triggers fires.
    """

    engine: WakeWordEngineName
    enabled: bool


class WakeTriggerAddAction(SpeechRecognitionAction):
    """Add a wake-word trigger to an engine."""

    engine: WakeWordEngineName
    id: str
    label: str
    mode: WakeMode
    value: str
    sensitivity: float = 0.5


class WakeTriggerRemoveAction(SpeechRecognitionAction):
    """Remove the trigger with the matching ``id`` from an engine."""

    engine: WakeWordEngineName
    id: str


class SpeechRecognitionSetAssistantEnabledAction(SpeechRecognitionAction):
    """Turn the assistant (QUICK_CHAT/CONVERSATION) wake modes on or off.

    Backs the "Assistant: Turn On/Off" voice command — toggles the QUICK_CHAT and
    CONVERSATION entries of ``enabled_wake_modes`` together. When off, the manager
    stops streaming those triggers; INTENTS and STOP_TALKING are unaffected.
    """

    enabled: bool


class SpeechRecognitionSetWakeModeEnabledAction(SpeechRecognitionAction):
    """Arm or disarm a single wake mode (shortcut / short chat / conversation).

    Backs the per-mode switches in Settings ▸ Assistant ▸ Wake Up. ``STOP_TALKING``
    has no switch and is ignored by the reducer.
    """

    mode: WakeMode
    enabled: bool


# --- Wake-word model lifecycle (download / upload / delete) ------------------


class WakeWordDownloadModelsAction(SpeechRecognitionAction):
    """Action to download the default models for a wake word engine (batch)."""

    engine_name: WakeWordEngineName


class WakeWordDownloadModelAction(SpeechRecognitionAction):
    """Download one catalog model for a wake-word engine.

    The per-model counterpart of :class:`WakeWordDownloadModelsAction`, used by
    engines whose models are browsed and fetched individually (microWakeWord).
    The reducer marks the engine as downloading and emits
    :class:`WakeWordDownloadModelEvent`; the service does the fetch off-reducer.
    """

    engine: WakeWordEngineName
    model_id: str


class WakeWordDeleteModelAction(SpeechRecognitionAction):
    """Delete a downloaded/uploaded wake-word model from disk.

    The reducer drops any trigger referencing the stem and emits
    :class:`WakeWordDeleteModelEvent`; the service deletes the file off-reducer.
    """

    engine: WakeWordEngineName
    model_id: str


class WakeWordSetAvailableModelsAction(SpeechRecognitionAction):
    """Report the on-disk model pool for an engine.

    Dispatched by the service after a (filesystem) scan/download/upload/delete so
    the reducer stays pure and only records the result.
    """

    engine: WakeWordEngineName
    models: tuple[str, ...]


class WakeWordSetModelsStatusAction(SpeechRecognitionAction):
    """Report a wake-word engine's default-model download status.

    Dispatched by the service after a (filesystem) availability check, so the
    reducer stays pure and only records the result.
    """

    engine_name: WakeWordEngineName
    status: WakeWordModelStatus


# --- Voice commands (intents) -----------------------------------------------


class SpeechRecognitionAddCommandAction(SpeechRecognitionAction):
    """Action to add a custom voice command."""

    id: str
    label: str
    phrases: list[str]
    action_keys: list[str]


class SpeechRecognitionUpdateCommandAction(SpeechRecognitionAction):
    """Action to replace the command with the matching ``id``."""

    id: str
    label: str
    phrases: list[str]
    action_keys: list[str]


class SpeechRecognitionRemoveCommandAction(SpeechRecognitionAction):
    """Action to remove the command with the matching ``id``."""

    id: str


class SpeechRecognitionRunCommandAction(SpeechRecognitionAction):
    """Run the voice command with the matching ``id`` (LLM tool path).

    Dispatched (over gRPC) by the assistant subprocess when the LLM calls the
    ``run_device_command`` tool for an utterance that stage-1 phrase matching
    missed. The reducer validates the id against ``intents`` and emits
    :class:`SpeechRecognitionBoundActionTriggeredEvent`; unknown ids are a
    no-op.
    """

    command_id: str


class SpeechRecognitionSetConversationEndPhrasesAction(SpeechRecognitionAction):
    """Replace the conversation end-of-turn phrases (a set of alternatives)."""

    phrases: tuple[str, ...]


class SpeechRecognitionIntent(Immutable):
    """A voice command: example phrases mapped to bindable-action keys.

    ``action_keys`` reference entries in the bindable-actions registry
    (:mod:`ubo_app.store.core.bindable_actions`); they are resolved and
    dispatched when one of the ``phrases`` is recognised.
    """

    id: str
    label: str
    phrases: list[str]
    action_keys: list[str]


class SpeechRecognitionCommandDescriptor(Immutable):
    """A command's id/label plus a few sample phrases, for LLM tool exposure.

    A trimmed, serialization-friendly view of :class:`SpeechRecognitionIntent`
    (patterns pre-expanded into concrete sample phrases) consumed by the
    assistant subprocess to build the ``run_device_command`` tool schema.
    """

    id: str
    label: str
    sample_phrases: list[str]


class SpeechRecognitionCommandsCatalog(Immutable):
    """Wrapper for the list of command descriptors.

    gRPC selectors can't return bare container types, so the assistant
    subprocess subscribes to this wrapped view (mirrors
    ``mcp.EnabledMcpServersWithMetadata``).
    """

    items: list[SpeechRecognitionCommandDescriptor] = field(default_factory=list)


class SpeechRecognitionReportWakeWordDetectionAction(SpeechRecognitionAction):
    """Action to report wake word detection.

    ``trigger_id`` identifies which configured trigger fired (the reducer resolves
    its mode); ``phrase`` is the human-readable value (forwarded to
    ``WakePhraseTriggerSource`` and the mic-buffer dump).
    """

    engine_name: str
    trigger_id: str
    phrase: str = ''


class SpeechRecognitionTriggerModeAction(SpeechRecognitionAction):
    """Trigger an assistant wake *mode* directly (engine-agnostic).

    The single entry point for the mode→effect map: the audio detection handler
    delegates here after resolving its trigger, and the per-mode bindable actions
    (used by Infrared remote codes) return this. ``phrase``/``detector`` are
    forwarded to the assistant trigger source / stop metadata.
    """

    mode: WakeMode
    phrase: str = ''
    detector: str = ''


class SpeechRecognitionSetAssistantListeningAction(SpeechRecognitionAction):
    """Arm/disarm stage-1 command matching for a quick-chat assistant session.

    Dispatched by the speech-recognition service's autorun tracking the
    assistant's ``is_listening`` state: ``active=True`` when a QUICK_CHAT
    wake-phrase session starts listening (``audio_source`` is that session's
    mic; ``''`` = on-device), ``active=False`` on any stop path. The reducer
    only moves ``IDLE`` → ``ASSISTANT_WAITING`` and back.
    """

    active: bool
    audio_source: str = ''


class SpeechRecognitionReportIntentDetectionAction(SpeechRecognitionAction):
    """Action to report intent detection."""

    intent: SpeechRecognitionIntent
    text: str


class SpeechRecognitionReportIntentTimeoutAction(SpeechRecognitionAction):
    """Action reporting that intent listening elapsed without a command."""


class SpeechRecognitionReportSpeechAction(SpeechRecognitionAction):
    """Action to report speech raw audio and recognized text."""

    engine_name: SpeechRecognitionEngineName
    text: str
    audio: bytes


class SpeechRecognitionEvent(BaseEvent):
    """Base class for speech recognition events."""


class WakeWordDownloadModelsEvent(SpeechRecognitionEvent):
    """Event asking the service to download a wake-word engine's models."""

    engine_name: WakeWordEngineName


class WakeWordDownloadModelEvent(SpeechRecognitionEvent):
    """Event asking the service to download one catalog model."""

    engine: WakeWordEngineName
    model_id: str


class WakeWordDeleteModelEvent(SpeechRecognitionEvent):
    """Event asking the service to delete a wake-word model file off-reducer."""

    engine: WakeWordEngineName
    model_id: str


class SpeechRecognitionReportTextEvent(SpeechRecognitionEvent):
    """Event to report stream of recognized text."""

    timestamp: float
    text: str


class SpeechRecognitionBoundActionTriggeredEvent(SpeechRecognitionEvent):
    """Event emitted when a recognised command's action keys should fire.

    The speech-recognition service's handler resolves each ``action_keys``
    entry against the bindable-actions registry and dispatches the produced
    actions (keeping the reducer pure).
    """

    action_keys: list[str]
    phrase: str


class SpeechRecognitionStatus(StrEnum):
    """State for speech recognition service.

    ``INTENTS_WAITING``: an INTENTS wake word armed the standalone command
    listener (blue ring, 10 s timeout).
    ``ASSISTANT_WAITING``: a QUICK_CHAT assistant session is listening and
    stage-1 command matching is armed alongside it — Vosk recognizes against
    the intent-phrase grammar and a match short-circuits the LLM. Lifetime is
    bound to the assistant's ``is_listening``, not a timeout.
    """

    IDLE = 'idle'
    INTENTS_WAITING = 'intents_waiting'
    ASSISTANT_WAITING = 'assistant_waiting'


class SpeechRecognitionEngineName(StrEnum):
    """Available speech recognition engines.

    Only Vosk remains (offline, in-core). The enum is retained because the
    detection report actions carry an ``engine_name`` that is part of the
    serialized RPC contract and the wake-phrase trigger metadata.
    """

    VOSK = 'vosk'


class WakeWordTrigger(Immutable):
    """One thing an engine listens for, mapped to an assistant mode.

    ``value`` is an opaque per-engine string:
    - Vosk:         the spoken phrase text.
    - OpenWakeWord: the model id (file stem, e.g. ``hey_jarvis_v0.1``).
    - Picovoice:    the keyword / ``.ppn`` id (future).

    Triggers are add/remove only — there is no per-trigger enable flag; a trigger's
    presence means it is active (subject to the engine's enable + its mode being in
    ``enabled_wake_modes``).

    ``sensitivity`` (0.0-1.0, default 0.5) is how readily the trigger fires — higher
    is more sensitive. It only applies to confidence-scored engines (OpenWakeWord),
    where the engine activates when ``confidence >= 1 - sensitivity``; phrase-match
    engines (Vosk) ignore it.
    """

    id: str
    label: str
    mode: WakeMode
    value: str
    sensitivity: float = 0.5


def clamp_sensitivity(value: object) -> float:
    """Clamp a trigger sensitivity into ``[0.0, 1.0]``.

    Sensitivity reaches the confidence-scored engines as ``confidence >= 1 -
    sensitivity`` (see ``openwakeword_engine``), so an out-of-range or non-finite
    value silently degrades into "never fires" / "fires on anything". The Web UI
    clamps its slider, but a remote-dispatched ``WakeTriggerAddAction`` or a
    hand-edited persisted blob can supply a negative, ``>1``, ``NaN`` or
    non-numeric value — sanitize it here, at the (trusted) state boundary.
    Non-numeric / non-finite input falls back to the ``0.5`` default.
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, number)) if math.isfinite(number) else 0.5


class WakeWordEngineConfig(Immutable):
    """One wake-word engine and the triggers it listens for."""

    engine: WakeWordEngineName
    enabled: bool
    triggers: tuple[WakeWordTrigger, ...]


# Canonical mode order — seed/rendering rely on it being stable.
_MODE_ORDER: tuple[WakeMode, ...] = (
    WakeMode.INTENTS,
    WakeMode.QUICK_CHAT,
    WakeMode.CONVERSATION,
    WakeMode.STOP_TALKING,
    WakeMode.HOME_ASSISTANT,
)


def order_wake_modes(modes: Iterable[WakeMode]) -> tuple[WakeMode, ...]:
    """Return *modes* deduplicated in canonical :data:`_MODE_ORDER` order."""
    present = set(modes)
    return tuple(mode for mode in _MODE_ORDER if mode in present)
_DEFAULT_MODE_PHRASES: dict[WakeMode, tuple[str, ...]] = {
    WakeMode.INTENTS: (INTENTS_WAKE_WORD,),
    WakeMode.QUICK_CHAT: (ASSISTANT_QUICK_CHAT_WAKE_PHRASE,),
    WakeMode.CONVERSATION: (ASSISTANT_CONVERSATION_WAKE_WORD,),
    WakeMode.STOP_TALKING: (ASSISTANT_STOP_TALKING_PHRASE,),
    WakeMode.HOME_ASSISTANT: (HOME_ASSISTANT_WAKE_PHRASE,),
}

# (mode, phrases) entries — the source for seeding/migrating Vosk triggers.
_SlotEntry = tuple[WakeMode, tuple[str, ...]]


def _default_slot_entries() -> list[_SlotEntry]:
    return [(mode, _DEFAULT_MODE_PHRASES[mode]) for mode in _MODE_ORDER]


def _legacy_slot_entries() -> list[_SlotEntry]:
    """Build slot entries from the Phase-1 persistent keys (one-shot migration).

    Phase 1 stored four single-phrase keys. When neither ``wake_engines`` nor
    ``wake_slots`` is present we read those so a branch user doesn't lose their
    phrases on upgrade. The legacy keys then go stale.
    """
    legacy_phrase = {
        WakeMode.INTENTS: read_from_persistent_store(
            'speech_recognition:intents_wake_word',
            default=INTENTS_WAKE_WORD,
        ),
        WakeMode.QUICK_CHAT: read_from_persistent_store(
            'speech_recognition:quick_chat_wake_phrase',
            default=ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
        ),
        WakeMode.CONVERSATION: read_from_persistent_store(
            'speech_recognition:conversation_wake_phrase',
            default=ASSISTANT_CONVERSATION_WAKE_WORD,
        ),
        WakeMode.STOP_TALKING: read_from_persistent_store(
            'speech_recognition:stop_talking_phrase',
            default=ASSISTANT_STOP_TALKING_PHRASE,
        ),
        # Postdates the Phase-1 layout, so it has no legacy key to read.
        WakeMode.HOME_ASSISTANT: HOME_ASSISTANT_WAKE_PHRASE,
    }
    return [(mode, (legacy_phrase[mode],)) for mode in _MODE_ORDER]


def _vosk_triggers_from_entries(
    entries: list[_SlotEntry],
) -> tuple[WakeWordTrigger, ...]:
    """Expand (mode, phrases) entries into one trigger per phrase.

    Seed/migrated triggers get *deterministic* ids (``<mode>-<index>``) so default
    state serializes identically across runs (snapshot-stable); user-added
    triggers get uuids at runtime.
    """
    triggers: list[WakeWordTrigger] = []
    for mode, phrases in entries:
        for index, phrase in enumerate(phrases):
            triggers.append(
                WakeWordTrigger(
                    id=f'{mode.value}-{index}',
                    label=phrase,
                    mode=mode,
                    value=phrase,
                ),
            )
    return tuple(triggers)


def _default_engine_configs(
    vosk_entries: list[_SlotEntry] | None = None,
) -> tuple[WakeWordEngineConfig, ...]:
    return (
        WakeWordEngineConfig(
            engine=WakeWordEngineName.VOSK,
            enabled=True,
            triggers=_vosk_triggers_from_entries(
                vosk_entries if vosk_entries is not None else _default_slot_entries(),
            ),
        ),
        WakeWordEngineConfig(
            engine=WakeWordEngineName.OPENWAKEWORD,
            enabled=False,
            triggers=(),
        ),
        WakeWordEngineConfig(
            engine=WakeWordEngineName.MICROWAKEWORD,
            enabled=False,
            triggers=(),
        ),
    )


def _parse_wake_slots() -> list[tuple[WakeMode, tuple[str, ...], bool]] | None:
    """Parse the legacy ``wake_slots`` blob as (mode, phrases, enabled), or None.

    Returns None when the key is absent or malformed. Carries each slot's old
    ``enabled`` flag so migration can honour a disabled assistant / disabled modes
    (the new model dropped per-trigger enable).
    """
    raw = read_from_persistent_store('speech_recognition:wake_slots', default=None)
    if not raw:
        return None
    try:
        slots = json.loads(raw)
        parsed: list[tuple[WakeMode, tuple[str, ...], bool]] = []
        for slot in slots:
            mode = WakeMode(slot['mode'])
            phrases = tuple(slot.get('phrases') or _DEFAULT_MODE_PHRASES[mode])
            parsed.append((mode, phrases, bool(slot.get('enabled', True))))
    except (json.JSONDecodeError, TypeError, KeyError, ValueError):
        return None
    return parsed


def _migrate_from_wake_slots() -> tuple[WakeWordEngineConfig, ...]:
    """Build engine configs from the old ``wake_slots`` blob (or legacy keys)."""
    raw = read_from_persistent_store('speech_recognition:wake_slots', default=None)
    if not raw:
        return _default_engine_configs(_legacy_slot_entries())
    parsed = _parse_wake_slots()
    if parsed is None:  # present but malformed
        return _default_engine_configs()
    # This blob migrates only the phrases (trigger set); the per-mode arm/disarm
    # now lives in ``enabled_wake_modes`` (fresh-defaults on). A slot the user had
    # disabled here maps to "removed" — its phrase isn't carried over.
    entries: list[_SlotEntry] = [
        (mode, phrases) for mode, phrases, enabled in parsed if enabled
    ]
    return _default_engine_configs(entries)


def _config_from_json(entry: dict) -> WakeWordEngineConfig:
    """Rebuild one engine config from its persisted JSON dict."""
    return WakeWordEngineConfig(
        engine=WakeWordEngineName(entry['engine']),
        enabled=bool(entry.get('enabled', False)),
        triggers=tuple(
            WakeWordTrigger(
                id=trigger['id'],
                label=trigger['label'],
                mode=WakeMode(trigger['mode']),
                value=trigger['value'],
                # Older persisted triggers predate per-trigger sensitivity; a
                # hand-edited blob may also carry an out-of-range/non-finite value.
                sensitivity=clamp_sensitivity(trigger.get('sensitivity', 0.5)),
            )
            for trigger in entry.get('triggers', [])
        ),
    )


def _load_enabled_wake_modes() -> tuple[WakeMode, ...]:
    """Which wake modes are armed. Fresh installs get every mode on.

    Persisted as a JSON list of mode values under ``enabled_wake_modes``. Legacy
    assistant on/off keys are deliberately ignored — a device that had the
    assistant off comes back with everything on (product decision). Unknown values
    are dropped and ``STOP_TALKING`` (no switch) is always armed.
    """
    stored: object = read_from_persistent_store(
        'speech_recognition:enabled_wake_modes',
        default=None,
    )
    if not isinstance(stored, list):
        return _MODE_ORDER
    by_value = {mode.value: mode for mode in _MODE_ORDER}
    enabled = {by_value[value] for value in stored if value in by_value}
    enabled.add(WakeMode.STOP_TALKING)
    return order_wake_modes(enabled)


def _load_wake_engines() -> tuple[WakeWordEngineConfig, ...]:
    """Load wake engines from persistent storage, migrating/falling back.

    Stored as a JSON list of ``{engine, enabled, triggers:[{id,label,mode,value,
    enabled}]}``. Absent → migrate the old ``wake_slots`` key. Malformed → defaults.
    Always ensures every :class:`WakeWordEngineName` is represented.
    """
    raw = read_from_persistent_store('speech_recognition:wake_engines', default=None)
    if not raw:
        return _migrate_from_wake_slots()
    try:
        data = json.loads(raw)
        configs = [_config_from_json(entry) for entry in data]
    except (json.JSONDecodeError, TypeError, KeyError, ValueError):
        return _default_engine_configs()
    present = {config.engine for config in configs}
    configs.extend(
        config
        for config in _default_engine_configs()
        if config.engine not in present
    )
    return tuple(configs)


class SpeechRecognitionState(Immutable):
    """State for speech recognition service."""

    intents: list[SpeechRecognitionIntent] = field(default_factory=list)
    wake_engines: tuple[WakeWordEngineConfig, ...] = field(
        default_factory=_load_wake_engines,
    )
    # Wake modes currently armed. A mode absent here has its wake triggers dropped
    # (EnginesManager) and any stray detection swallowed (reducer). STOP_TALKING is
    # always armed and has no switch; fresh installs default to every mode on.
    enabled_wake_modes: tuple[WakeMode, ...] = field(
        default_factory=_load_enabled_wake_modes,
    )
    # OpenWakeWord model stems available on disk (downloaded defaults + uploaded
    # customs). Derived from disk by the service at startup; not persisted.
    openwakeword_models: tuple[str, ...] = field(default_factory=tuple)
    # microWakeWord model ids available on disk (downloaded from the catalog).
    # Derived from disk by the service at startup; not persisted, same as above.
    microwakeword_models: tuple[str, ...] = field(default_factory=tuple)
    conversation_end_phrases: tuple[str, ...] = field(
        default=read_from_persistent_store(
            'speech_recognition:conversation_end_phrases',
            mapper=tuple,
            default=ASSISTANT_CONVERSATION_END_PHRASES,
        ),
    )
    status: SpeechRecognitionStatus = SpeechRecognitionStatus.IDLE
    # The mic source of the quick-chat session stage-1 matching is armed for
    # (only meaningful while ``status`` is ``ASSISTANT_WAITING``). ``''`` = the
    # on-device system mic — the only source Vosk consumes, so a non-empty
    # value (web mic) keeps the Vosk grammar disarmed.
    assistant_session_audio_source: str = ''
    # Trimmed mirror of ``intents`` (patterns expanded into sample phrases) for
    # the assistant subprocess's ``run_device_command`` LLM tool. Rebuilt by the
    # reducer at every intents write site.
    commands_catalog: SpeechRecognitionCommandsCatalog = field(
        default_factory=SpeechRecognitionCommandsCatalog,
    )
    wake_word_models_status: tuple[WakeWordModelStatusEntry, ...] = field(
        default_factory=tuple,
    )
    # Ids of the default commands that have already been offered to this device.
    # Lets a release add new defaults to an existing install without resurrecting
    # defaults the user deliberately deleted. See ``commands.load_or_seed_commands``.
    seeded_default_ids: tuple[str, ...] = field(default_factory=tuple)


def engine_config(
    state: SpeechRecognitionState,
    engine: WakeWordEngineName,
) -> WakeWordEngineConfig | None:
    """Return the config for *engine*, or None if not present."""
    return next(
        (config for config in state.wake_engines if config.engine == engine),
        None,
    )


def model_status(
    state: SpeechRecognitionState,
    engine: WakeWordEngineName,
) -> WakeWordModelStatus | None:
    """Return *engine*'s recorded model status, or None if unset."""
    return next(
        (
            entry.status
            for entry in state.wake_word_models_status
            if entry.engine == engine
        ),
        None,
    )


def set_model_status(
    statuses: tuple[WakeWordModelStatusEntry, ...],
    engine: WakeWordEngineName,
    status: WakeWordModelStatus,
    model_id: str = '',
) -> tuple[WakeWordModelStatusEntry, ...]:
    """Return *statuses* with *engine*'s status upserted to *status*."""
    return (
        *(entry for entry in statuses if entry.engine != engine),
        WakeWordModelStatusEntry(engine=engine, status=status, model_id=model_id),
    )


def downloading_model_id(
    state: SpeechRecognitionState,
    engine: WakeWordEngineName,
) -> str:
    """Return the model *engine* is currently downloading, or ``''`` if none."""
    return next(
        (
            entry.model_id
            for entry in state.wake_word_models_status
            if entry.engine == engine
            and entry.status == WakeWordModelStatus.DOWNLOADING
        ),
        '',
    )


def trigger_by_id(
    state: SpeechRecognitionState,
    engine: WakeWordEngineName,
    trigger_id: str,
) -> WakeWordTrigger | None:
    """Return the trigger with *trigger_id* on *engine*, or None."""
    config = engine_config(state, engine)
    if config is None:
        return None
    return next(
        (trigger for trigger in config.triggers if trigger.id == trigger_id),
        None,
    )
