"""Definitions for assistant actions, events and state."""

from __future__ import annotations

import json
from dataclasses import field
from enum import StrEnum
from typing import TYPE_CHECKING, TypeAlias

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.constants.assistant import (
    ASSISTANT_CONVERSATION_END_PHRASES,
    ASSISTANT_CONVERSATION_SILENCE_TIMEOUT_SECONDS,
    ASSISTANT_CONVERSATION_WAKE_WORD,
    ASSISTANT_DEFAULT_SILENCE_TIMEOUT_SECONDS,
    ASSISTANT_QUICK_CHAT_WAKE_PHRASE,
    DEFAULT_LLM_ANTHROPIC_MODEL,
    DEFAULT_LLM_CEREBRAS_MODEL,
    DEFAULT_LLM_DEEPSEEK_MODEL,
    DEFAULT_LLM_GENERIC_MODEL,
    DEFAULT_LLM_GOOGLE_MODEL,
    DEFAULT_LLM_GROK_MODEL,
    DEFAULT_LLM_MISTRAL_MODEL,
    DEFAULT_LLM_OLLAMA_MODEL,
    DEFAULT_LLM_OLLAMA_ONPREM_MODEL,
    DEFAULT_LLM_OPENAI_MODEL,
    DEFAULT_LLM_OPENROUTER_MODEL,
    DEFAULT_LLM_QWEN_MODEL,
    DEFAULT_LLM_VENICE_MODEL,
)
from ubo_app.utils.persistent_store import read_from_persistent_store

if TYPE_CHECKING:
    from ubo_app.store.services.audio import AudioSample
    from ubo_app.store.services.keypad import Key


class AssistantSTTName(StrEnum):
    """Available assistant speech-to-text engines."""

    VOSK = 'vosk'
    GOOGLE_SEGMENTED = 'google_segmented'
    GOOGLE = 'google'
    OPENAI = 'openai'
    DEEPGRAM = 'deepgram'
    ASSEMBLYAI = 'assemblyai'
    VENICE = 'venice'


class AssistantLLMName(StrEnum):
    """Available assistant llms."""

    OLLAMA = 'ollama'
    OLLAMA_ONPREM = 'ollama_onprem'
    GOOGLE = 'google_vertex'
    OPENAI = 'openai'
    GROK = 'grok'
    CEREBRAS = 'cerebras'
    ANTHROPIC = 'anthropic'
    QWEN = 'qwen'
    DEEPSEEK = 'deepseek'
    OPENROUTER = 'openrouter'
    MISTRAL = 'mistral'
    VENICE = 'venice'
    GENERIC = 'generic_llm'


DEFAULT_MODELS = {
    AssistantLLMName.OLLAMA: DEFAULT_LLM_OLLAMA_MODEL,
    AssistantLLMName.OLLAMA_ONPREM: DEFAULT_LLM_OLLAMA_ONPREM_MODEL,
    AssistantLLMName.GOOGLE: DEFAULT_LLM_GOOGLE_MODEL,
    AssistantLLMName.OPENAI: DEFAULT_LLM_OPENAI_MODEL,
    AssistantLLMName.GROK: DEFAULT_LLM_GROK_MODEL,
    AssistantLLMName.CEREBRAS: DEFAULT_LLM_CEREBRAS_MODEL,
    AssistantLLMName.ANTHROPIC: DEFAULT_LLM_ANTHROPIC_MODEL,
    AssistantLLMName.QWEN: DEFAULT_LLM_QWEN_MODEL,
    AssistantLLMName.DEEPSEEK: DEFAULT_LLM_DEEPSEEK_MODEL,
    AssistantLLMName.OPENROUTER: DEFAULT_LLM_OPENROUTER_MODEL,
    AssistantLLMName.MISTRAL: DEFAULT_LLM_MISTRAL_MODEL,
    AssistantLLMName.VENICE: DEFAULT_LLM_VENICE_MODEL,
    AssistantLLMName.GENERIC: DEFAULT_LLM_GENERIC_MODEL,
}


def _load_selected_models(value: str) -> dict[AssistantLLMName, str]:
    """Load selected LLM models from persistent storage."""
    try:
        models = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return DEFAULT_MODELS.copy()
    if not isinstance(models, dict):
        return DEFAULT_MODELS.copy()
    selected_models = DEFAULT_MODELS.copy()
    for key, model in models.items():
        try:
            llm_name = AssistantLLMName(key)
        except ValueError:
            continue
        selected_models[llm_name] = str(model)
    return selected_models


class GenericLLMProvider(Immutable):
    """A named OpenAI-compatible LLM provider added by the user (or a service)."""

    provider_id: str
    label: str


def generic_llm_instance_key(provider_id: str) -> str:
    """Menu/engine instance key for a named generic LLM provider."""
    return f'{AssistantLLMName.GENERIC}:{provider_id}'


def _load_generic_llm_providers(value: str) -> tuple[GenericLLMProvider, ...]:
    """Load named generic LLM providers from persistent storage."""
    try:
        entries = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(entries, list):
        return ()
    providers: list[GenericLLMProvider] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        provider_id = entry.get('provider_id')
        label = entry.get('label')
        if isinstance(provider_id, str) and provider_id and isinstance(label, str):
            providers.append(
                GenericLLMProvider(provider_id=provider_id, label=label),
            )
    return tuple(providers)


def _load_ollama_thinking_enabled(value: str) -> dict[str, bool]:
    """Load per-model Ollama thinking flags from persistent storage."""
    try:
        flags = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(flags, dict):
        return {}
    return {str(k): bool(v) for k, v in flags.items()}


# Hard-coded fallback. The full catalog lives in
# ``ubo_app/engines/piper_catalog.py`` — kept out of this module to avoid
# pulling the localization import into the state-schema layer.
DEFAULT_PIPER_VOICE_ID = 'en/en_US/kristin/medium/en_US-kristin-medium'

# Hard-coded fallback. The full catalog lives in
# ``ubo_app/engines/vosk_catalog.py``.
DEFAULT_VOSK_MODEL_ID = 'vosk-model-small-en-us-0.15'


def _load_piper_voice(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return DEFAULT_PIPER_VOICE_ID


# Hard-coded fallback. Full catalog lives in
# ``ubo_app/engines/kokoro_catalog.py``; kept out of this module to
# avoid pulling the localization import into the state-schema layer.
DEFAULT_KOKORO_VOICE_ID = 'af_heart'


def _load_kokoro_voice(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return DEFAULT_KOKORO_VOICE_ID


def _load_vosk_model(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return DEFAULT_VOSK_MODEL_ID


class AssistantTTSName(StrEnum):
    """Available assistant text-to-speech engines."""

    PIPER = 'piper'
    KOKORO = 'kokoro'
    GOOGLE = 'google'
    OPENAI = 'openai'
    ELEVENLABS = 'elevenlabs'
    RIME = 'rime'
    VENICE = 'venice'


class AssistantImageGeneratorName(StrEnum):
    """Available assistant image generator engines."""

    GOOGLE = 'google'
    OPENAI = 'openai'


class AssistantPipelineStage(StrEnum):
    """A stage in the assistant pipeline.

    A programmatic request runs a *contiguous* sub-chain of these, in this order.
    Also doubles as the ``source`` discriminator on
    :class:`AssistanceTextFrame` so consumers can route by enum identity instead
    of string-matching.
    """

    STT = 'stt'
    LLM = 'llm'
    TTS = 'tts'


# ``AssistantReportAction.source_id`` / ``AssistantHandleReportEvent.source_id``
# identifies which *pipeline* produced a frame. Two well-known values exist;
# everywhere they're used should import these constants instead of repeating
# the literal — a typo in a comparison silently breaks chat routing.
LIVE_PIPELINE_SOURCE_ID = 'pipecat'
REQUEST_PIPELINE_SOURCE_ID = 'assistant_request'


class McpServerType(StrEnum):
    """MCP server types."""

    STDIO = 'stdio'
    SSE = 'sse'


class StdioMcpConfig(Immutable):
    """Configuration for stdio MCP servers."""

    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


class SseMcpConfig(Immutable):
    """Configuration for SSE MCP servers."""

    url: str


class McpServerMetadata(Immutable):
    """Metadata for an MCP server."""

    server_id: str  # Format: {name}_{uuid}
    name: str  # User-friendly name
    type: McpServerType  # Server type enum
    config: StdioMcpConfig | SseMcpConfig  # Typed config - protobuf oneof


class EnabledMcpServersWithMetadata(Immutable):
    """Wrapper for list of enabled MCP servers with metadata.

    This wrapper is needed because gRPC selectors don't support
    container types (lists) directly.
    """

    items: list[McpServerMetadata] = field(default_factory=list)


class AssistantTriggerSource(Immutable):
    """Base class identifying how the assistant was asked to start listening."""


class WakePhraseTriggerSource(AssistantTriggerSource):
    """Listening was triggered by a recognised wake phrase."""

    phrase: str
    detector: str = 'vosk'


class KeypadTriggerSource(AssistantTriggerSource):
    """Listening was triggered by a physical keypad key."""

    key: Key
    mode: str = 'press'  # 'press' (depth=1 home) or 'hold' (in-menu hold)


class InfraredTriggerSource(AssistantTriggerSource):
    """Listening was triggered by an infrared remote code."""

    protocol: str
    scancode: str
    label: str | None = None


class GrpcTriggerSource(AssistantTriggerSource):
    """Listening was triggered programmatically over gRPC."""


class DesktopTriggerSource(AssistantTriggerSource):
    """Listening was triggered by the desktop GUI client (e.g. V key)."""


AssistantTriggerSourceUnion: TypeAlias = (
    WakePhraseTriggerSource
    | KeypadTriggerSource
    | InfraredTriggerSource
    | GrpcTriggerSource
    | DesktopTriggerSource
)


class AssistantStopReason(Immutable):
    """Base class explaining why a listening session is ending."""


class UserStopReason(AssistantStopReason):
    """Stop initiated by the user via the same family as the start trigger."""

    source: AssistantTriggerSourceUnion


class SilenceTimeoutStopReason(AssistantStopReason):
    """Stop dispatched by the pipeline after a configured silence window."""

    silence_seconds: float


class EndOfTurnPhraseStopReason(AssistantStopReason):
    """Stop dispatched by the pipeline after detecting an end-of-turn phrase."""

    phrase: str
    matched_text: str


class ExternalStopReason(AssistantStopReason):
    """Stop initiated by something outside the user/pipeline taxonomy."""


class StopTalkingPhraseStopReason(AssistantStopReason):
    """Stop dispatched after the user said the always-on stop-talking phrase.

    Distinct from :class:`EndOfTurnPhraseStopReason` (which is detected inside
    the Pipecat pipeline by the configured end-of-turn phrases) — this reason
    fires when the Vosk-side always-on stop phrase ("okay enough" by default)
    is heard and the user wants to fully exit the interaction.
    """


class BotStartedSpeakingStopReason(AssistantStopReason):
    """Stop dispatched when the assistant begins speaking (TTS playback starts).

    The device has no acoustic echo cancellation, so listening must end the
    instant the bot starts talking — otherwise the open mic captures the bot's
    own speech and confuses the pipeline.
    """


AssistantStopReasonUnion: TypeAlias = (
    UserStopReason
    | SilenceTimeoutStopReason
    | EndOfTurnPhraseStopReason
    | ExternalStopReason
    | StopTalkingPhraseStopReason
    | BotStartedSpeakingStopReason
)


class AssistantTriggerPolicyMatcher(Immutable):
    """Base class for matchers that select a policy for a trigger source."""


class WakePhraseMatcher(AssistantTriggerPolicyMatcher):
    """Match a wake-phrase trigger by phrase string (case-insensitive equality)."""

    phrase: str


class KeypadMatcher(AssistantTriggerPolicyMatcher):
    """Match a keypad trigger optionally narrowed by key."""

    key: Key | None = None


class InfraredMatcher(AssistantTriggerPolicyMatcher):
    """Match an infrared trigger optionally narrowed by protocol/scancode."""

    protocol: str | None = None
    scancode: str | None = None


class AnySourceMatcher(AssistantTriggerPolicyMatcher):
    """Fallback matcher — always matches. Use last in the policy list."""


AssistantTriggerPolicyMatcherUnion: TypeAlias = (
    WakePhraseMatcher | KeypadMatcher | InfraredMatcher | AnySourceMatcher
)


class AssistantTurnCompletionMode(StrEnum):
    """How a listening session decides the user's turn is finished.

    ``SILENCE`` completes the turn after ``silence_timeout_seconds`` of
    continuous quiet (and/or an end-of-turn phrase). ``MANUAL`` is push-to-talk:
    the turn never completes on silence while listening — it completes only when
    the session ends (button release / listen toggle off), flushing whatever was
    accumulated.
    """

    SILENCE = 'silence'
    MANUAL = 'manual'


class AssistantTriggerPolicy(Immutable):
    """Controls how the pipeline decides the user has stopped speaking."""

    silence_timeout_seconds: float | None = None
    end_of_turn_phrases: tuple[str, ...] = ()
    completion_mode: AssistantTurnCompletionMode = AssistantTurnCompletionMode.SILENCE


class AssistantTriggerPolicyEntry(Immutable):
    """A (matcher, policy) pair in the per-trigger policy table."""

    matcher: AssistantTriggerPolicyMatcherUnion
    policy: AssistantTriggerPolicy


def _default_policies() -> tuple[AssistantTriggerPolicyEntry, ...]:
    """Build the default policy table.

    Resolved at runtime so wake-phrase env-var overrides are picked up.
    Order is most-specific-first; ``AnySourceMatcher`` must remain last.
    """
    return (
        # Conversation: tolerate long pauses — complete on an end-of-turn phrase
        # OR after a long silence window.
        AssistantTriggerPolicyEntry(
            matcher=WakePhraseMatcher(phrase=ASSISTANT_CONVERSATION_WAKE_WORD),
            policy=AssistantTriggerPolicy(
                silence_timeout_seconds=ASSISTANT_CONVERSATION_SILENCE_TIMEOUT_SECONDS,
                end_of_turn_phrases=ASSISTANT_CONVERSATION_END_PHRASES,
            ),
        ),
        # Quick chat: single short turn, complete after a brief silence.
        AssistantTriggerPolicyEntry(
            matcher=WakePhraseMatcher(phrase=ASSISTANT_QUICK_CHAT_WAKE_PHRASE),
            policy=AssistantTriggerPolicy(
                silence_timeout_seconds=ASSISTANT_DEFAULT_SILENCE_TIMEOUT_SECONDS,
            ),
        ),
        # Keypad and infrared are push-to-talk: accumulate while held / toggled
        # on, and only flush when the session ends (release / toggle off).
        AssistantTriggerPolicyEntry(
            matcher=KeypadMatcher(),
            policy=AssistantTriggerPolicy(
                completion_mode=AssistantTurnCompletionMode.MANUAL,
            ),
        ),
        AssistantTriggerPolicyEntry(
            matcher=InfraredMatcher(),
            policy=AssistantTriggerPolicy(
                completion_mode=AssistantTurnCompletionMode.MANUAL,
            ),
        ),
        # Unknown sources keep the conservative short-silence completion.
        AssistantTriggerPolicyEntry(
            matcher=AnySourceMatcher(),
            policy=AssistantTriggerPolicy(),
        ),
    )


def _matcher_matches(
    matcher: AssistantTriggerPolicyMatcherUnion,
    source: AssistantTriggerSourceUnion,
) -> bool:
    """Return True if *matcher* applies to *source*."""
    if isinstance(matcher, AnySourceMatcher):
        return True
    if isinstance(matcher, WakePhraseMatcher):
        return (
            isinstance(source, WakePhraseTriggerSource)
            and matcher.phrase.casefold() == source.phrase.casefold()
        )
    if isinstance(matcher, KeypadMatcher):
        if not isinstance(source, KeypadTriggerSource):
            return False
        return matcher.key is None or matcher.key == source.key
    if isinstance(matcher, InfraredMatcher):
        if not isinstance(source, InfraredTriggerSource):
            return False
        if matcher.protocol is not None and matcher.protocol != source.protocol:
            return False
        return matcher.scancode is None or matcher.scancode == source.scancode
    return False


def resolve_policy(
    policies: tuple[AssistantTriggerPolicyEntry, ...],
    source: AssistantTriggerSourceUnion | None,
) -> AssistantTriggerPolicy | None:
    """Walk *policies* and return the first matching policy for *source*.

    Returns ``None`` when *source* is ``None`` (legacy callers) or when no
    matcher matches.
    """
    if source is None:
        return None
    for entry in policies:
        if _matcher_matches(entry.matcher, source):
            return entry.policy
    return None


class AssistantAction(BaseAction):
    """Base class for assistant actions."""


class AssistantSetIsActiveAction(AssistantAction):
    """Action to set the assistant active state."""

    is_active: bool


class AssistantSetSelectedSTTAction(AssistantAction):
    """Action to set the selected stt."""

    stt_name: AssistantSTTName


class AssistantSetSelectedLLMAction(AssistantAction):
    """Action to set the selected llm."""

    llm_name: AssistantLLMName


class AssistantSetSelectedTTSAction(AssistantAction):
    """Action to set the selected tts."""

    tts_name: AssistantTTSName


class AssistantSetSelectedImageGeneratorAction(AssistantAction):
    """Action to set the selected image generator."""

    image_generator_name: AssistantImageGeneratorName


class AssistantSetSelectedModelAction(AssistantAction):
    """Action to set the selected model."""

    model: str
    llm_name: AssistantLLMName | None = None


class AssistantDownloadOllamaModelAction(AssistantAction):
    """Action to download an Ollama model."""

    model: str


class AssistantSetOllamaDownloadedModelsAction(AssistantAction):
    """Replace the cached set of locally-downloaded Ollama models.

    Tags are stored **normalised** (lowercase + explicit ``:tag``) via
    ``normalize_model_tag()`` so consumers don't need to normalise on every
    render.
    """

    models: tuple[str, ...]


class AssistantSetOllamaModelCapabilitiesAction(AssistantAction):
    """Cache the result of ``ollama.Client.show(model).capabilities``."""

    model: str
    capabilities: tuple[str, ...]


class AssistantSetOllamaThinkingAction(AssistantAction):
    """Toggle thinking mode for a local Ollama model.

    Per-model and persisted. The reducer also emits
    ``AssistantOllamaThinkingChangedEvent`` so the subprocess can refresh
    its Pipecat service with the new ``think`` flag.
    """

    model: str
    enabled: bool


class AssistantSetSelectedPiperVoiceAction(AssistantAction):
    """Action to pick a Piper voice (path-style HuggingFace id).

    No event is emitted: the assistant subprocess tracks
    ``selected_piper_voice`` via a gRPC autorun and ``PiperTTSService``
    reconciles the loaded model before each utterance.
    """

    voice_id: str


class AssistantDownloadPiperVoiceAction(AssistantAction):
    """Action requesting download of a Piper voice's ``.onnx`` + JSON files."""

    voice_id: str


class AssistantSetPiperDownloadedVoicesAction(AssistantAction):
    """Replace the cached set of locally-downloaded Piper voice ids."""

    voices: tuple[str, ...]


class AssistantSetSelectedKokoroVoiceAction(AssistantAction):
    """Action to pick a Kokoro voice (id string, e.g. ``af_heart``).

    No event is emitted: the assistant subprocess tracks
    ``selected_kokoro_voice`` via a gRPC autorun and ``KokoroTTSService``
    updates its settings before the next utterance.
    """

    voice_id: str


class AssistantDownloadKokoroAction(AssistantAction):
    """Action requesting download of the Kokoro model + voices bundle.

    Kokoro ships ALL voices in a single ``voices-v1.0.bin`` plus the
    ``kokoro-v1.0.onnx`` model, so this is a one-shot download — the
    ``voice_id`` is carried only so the download notification can name
    the voice the user just picked.
    """

    voice_id: str


class AssistantSetKokoroDownloadedAction(AssistantAction):
    """Mark whether the Kokoro model + voices bundle is on disk."""

    downloaded: bool


class AssistantSetSelectedVoskModelAction(AssistantAction):
    """Action to pick a Vosk STT model (alphacephei model id).

    The assistant subprocess tracks ``selected_vosk_model`` via a gRPC
    autorun and re-points its ``VoskSTTService`` before the next
    utterance.
    """

    model_id: str


class AssistantDownloadVoskModelAction(AssistantAction):
    """Action requesting download of a Vosk model archive."""

    model_id: str


class AssistantSetVoskDownloadedModelsAction(AssistantAction):
    """Replace the cached set of locally-downloaded Vosk model ids."""

    models: tuple[str, ...]


class AssistanceFrame(Immutable):
    """An assistance frame."""

    is_last_frame: bool
    timestamp: float
    id: str
    index: int
    # Correlation id for programmatic pipeline requests; empty for live output.
    session_id: str = ''


class AssistanceTextFrame(AssistanceFrame):
    """A text assistance frame."""

    text: str
    # Originating pipeline stage. Set by every producer (the live
    # ``ubo_stt``/``ubo_llm`` pipelines and the request-pipeline
    # ``GRPCTerminalCollector``). ``None`` only on the wire-default path —
    # consumers should treat the value as the discriminator and never
    # parse the raw string.
    source: AssistantPipelineStage | None = None


class AssistanceAudioFrame(AssistanceFrame):
    """An audio assistance frame."""

    audio: AudioSample | None


class AssistanceImageFrame(AssistanceFrame):
    """An image assistance frame."""

    image: bytes
    width: int
    height: int
    format: str
    metadata: dict[str, str]


class AssistanceErrorFrame(AssistanceFrame):
    """An error assistance frame."""

    error: str


AcceptableAssistanceFrame: TypeAlias = (
    AssistanceTextFrame
    | AssistanceAudioFrame
    | AssistanceImageFrame
    | AssistanceErrorFrame
)


class AssistantReportAction(AssistantAction):
    """Action to report assistance from the assistant."""

    source_id: str
    data: AcceptableAssistanceFrame


class AssistantStartListeningAction(AssistantAction):
    """Action to start listening for the assistant.

    The optional ``source`` field carries structured metadata about *what*
    triggered the request (wake phrase, keypad button, infrared remote, …).
    Pipeline behaviour is selected per-source via ``AssistantState.policies``.

    ``audio_source`` is a separate axis: it identifies *which mic's audio* the
    session should consume (empty = on-device system mic; remote clients set a
    unique id). It must match the ``audio_source`` on incoming
    ``AudioReportSampleAction``s.
    """

    source: AssistantTriggerSourceUnion | None = None
    audio_source: str = ''


class AssistantStopListeningAction(AssistantAction):
    """Action to stop listening for the assistant.

    The optional ``reason`` field describes why listening is ending — either
    a user-initiated stop mirroring the start trigger, or a pipeline-internal
    stop (silence timeout, end-of-turn phrase).
    """

    reason: AssistantStopReasonUnion | None = None


class AssistantToggleListeningAction(AssistantAction):
    """Action to toggle listening state for the assistant.

    Source is forwarded to whichever direction the toggle resolves to.
    """

    source: AssistantTriggerSourceUnion | None = None
    audio_source: str = ''


class AssistantUpdateProvidersAction(AssistantAction):
    """Action to signal change in the state of available providers."""


class AssistantAddGenericLLMProviderAction(AssistantAction):
    """Action to add (or upsert by id) a named generic LLM provider."""

    provider_id: str
    label: str


class AssistantRemoveGenericLLMProviderAction(AssistantAction):
    """Action to remove a named generic LLM provider."""

    provider_id: str


class AssistantSelectGenericLLMProviderAction(AssistantAction):
    """Action to mark a named generic LLM provider as the active one.

    Dispatched by ``activate_provider`` *after* the provider's credentials
    have been copied into the canonical generic-LLM secret keys, so the
    resulting ``AssistantGenericLLMProviderChangedEvent`` always observes
    fresh secrets.
    """

    provider_id: str


class AssistantAddMcpServerAction(AssistantAction):
    """Action to add a new MCP server."""

    name: str
    type: McpServerType
    config: StdioMcpConfig | SseMcpConfig  # Typed config - protobuf oneof


class AssistantToggleMcpServerAction(AssistantAction):
    """Action to enable/disable an MCP server."""

    server_id: str


class AssistantDeleteMcpServerAction(AssistantAction):
    """Action to delete an MCP server."""

    server_id: str


class AssistantSyncMcpServersAction(AssistantAction):
    """Action to sync MCP servers from filesystem."""


class AssistantSetMcpServersAction(AssistantAction):
    """Action carrying MCP servers loaded from the filesystem.

    Dispatched by the assistant service's ``AssistantSyncMcpServersEvent``
    handler after it has read the on-disk configs, so the reducer can update
    the slice purely (no filesystem access inside the reduce cycle).
    """

    servers: list[McpServerMetadata]
    enabled_servers: list[str]


class AssistantStopTalkingAction(AssistantAction):
    """Action to silence the assistant immediately.

    Differs from a wake-phrase barge-in (``AssistantStartListeningAction``):
    this action stops the in-flight TTS playback and LLM response but does
    NOT start a new listening session — the user explicitly asked for quiet.
    """


class AssistantTranscribeAction(AssistantAction):
    """Shortcut action to request a one-shot transcription (STT-only)."""

    audio: bytes
    session_id: str
    sample_rate: int = 16000
    num_channels: int = 1
    stt_provider: AssistantSTTName | None = None


class AssistantSynthesizeAction(AssistantAction):
    """Shortcut action to request one-shot speech synthesis (TTS-only)."""

    text: str
    session_id: str
    tts_provider: AssistantTTSName | None = None


class AssistantCompleteAction(AssistantAction):
    """Shortcut action to request a one-shot LLM completion (LLM-only)."""

    text: str
    session_id: str
    llm_provider: AssistantLLMName | None = None
    system_prompt: str | None = None
    enable_tools: bool = False


class AssistantRunPipelineAction(AssistantAction):
    """Action to run a parametrized assistant pipeline.

    ``stages`` must be a contiguous sub-chain of ``[STT, LLM, TTS]``. The
    discrete ``AssistantTranscribe/Synthesize/CompleteAction``s are shortcuts
    the reducer maps onto the same canonical ``AssistantRunPipelineEvent``.
    """

    session_id: str
    stages: list[AssistantPipelineStage]
    audio: bytes = b''
    text: str = ''
    sample_rate: int = 16000
    num_channels: int = 1
    stt_provider: AssistantSTTName | None = None
    llm_provider: AssistantLLMName | None = None
    tts_provider: AssistantTTSName | None = None
    llm_model: str | None = None
    system_prompt: str | None = None
    enable_tools: bool = False


class AssistantEvent(BaseEvent):
    """Base class for assistant events."""


class AssistantStopTalkingEvent(AssistantEvent):
    """Event fired when the assistant should stop talking right now.

    Emitted by the assistant reducer in response to
    ``AssistantStopTalkingAction``. Consumed by the assistant subprocess to
    broadcast a Pipecat ``InterruptionFrame``.
    """


class AssistantDownloadOllamaModelEvent(AssistantEvent):
    """Event to download an Ollama model."""

    model: str


class AssistantHandleReportEvent(AssistantEvent):
    """Action to report assistance from the assistant."""

    source_id: str
    data: AcceptableAssistanceFrame


class AssistantUpdateProvidersEvent(AssistantEvent):
    """Event to signal change in the state of available providers."""


class AssistantModelChangedEvent(AssistantEvent):
    """Event signalling that the user picked a new model for an LLM provider.

    Emitted by the reducer in response to ``AssistantSetSelectedModelAction``
    so the assistant subprocess can hot-swap the active provider's Pipecat
    service. Goes through events because gRPC autorun cannot serialise the
    raw ``selected_models`` dict.
    """

    llm_name: AssistantLLMName
    model: str


class AssistantGenericLLMProviderChangedEvent(AssistantEvent):
    """Event signalling that the active named generic LLM provider changed.

    Emitted on *every* ``AssistantSelectGenericLLMProviderAction`` — even a
    re-select of the same id — because the ``selected_llm`` gRPC autorun in
    the assistant subprocess won't refire while its value stays
    ``generic_llm``, and credential edits of the active provider also need
    to reach the subprocess. The subprocess refreshes its generic LLM
    service from the canonical secret keys on this event.
    """

    provider_id: str


class AssistantGenericLLMProviderRemovedEvent(AssistantEvent):
    """Event signalling that a named generic LLM provider was removed.

    Handled by the assistant service (core side) to clear the provider's
    per-provider secrets — and the canonical copies when ``was_selected``
    is set — outside the reduce cycle.
    """

    provider_id: str
    was_selected: bool


class AssistantOllamaThinkingChangedEvent(AssistantEvent):
    """Event signalling that the user toggled Ollama thinking for a model.

    Sent so the assistant subprocess re-creates its local Ollama service
    with the new ``think`` flag.
    """

    model: str
    enabled: bool


class AssistantPiperVoiceChangedEvent(AssistantEvent):
    """Event signalling that the user picked a new Piper voice.

    Carries the voice id; the subprocess derives the on-disk model path
    itself so the event stays serialisable across the gRPC boundary.
    """

    voice_id: str


class AssistantDownloadPiperVoiceEvent(AssistantEvent):
    """Event requesting download of a Piper voice in the core process."""

    voice_id: str


class AssistantDownloadKokoroEvent(AssistantEvent):
    """Event requesting the one-shot Kokoro bundle download in core."""

    voice_id: str


class AssistantDownloadVoskModelEvent(AssistantEvent):
    """Event requesting download of a Vosk model in the core process."""

    model_id: str


class AssistantAddMcpServerEvent(AssistantEvent):
    """Event to add a new MCP server."""

    name: str
    type: McpServerType
    config: StdioMcpConfig | SseMcpConfig  # Typed config - protobuf oneof


class AssistantDeleteMcpServerEvent(AssistantEvent):
    """Event to delete an MCP server."""

    server_id: str


class AssistantToggleMcpServerEvent(AssistantEvent):
    """Event fired when an MCP server's enabled state is toggled.

    The reducer flips the in-memory ``enabled_mcp_servers`` purely; this event
    lets the assistant service persist the new state to the filesystem outside
    the reduce cycle.
    """

    server_id: str


class AssistantSyncMcpServersEvent(AssistantEvent):
    """Event requesting a reload of MCP servers from the filesystem.

    Emitted by the reducer in response to ``AssistantSyncMcpServersAction``;
    the assistant service reads the on-disk configs and dispatches
    ``AssistantSetMcpServersAction`` with the result.
    """


class AssistantRunPipelineEvent(AssistantEvent):
    """Event for the assistant service to run a parametrized pipeline.

    All provider/model fields are resolved — ``None`` action fields are filled
    in by the reducer from the current ``AssistantState`` selections. The
    discrete shortcut actions and ``AssistantRunPipelineAction`` all funnel
    into this one canonical event.

    Per-engine model/voice fields (``vosk_model_id``, ``piper_voice_id``,
    ``kokoro_voice_id``) carry the user's current selection so the request
    handler in the subprocess doesn't have to fall back to module-level
    defaults — keeping live and one-shot pipelines on the same model.
    """

    session_id: str
    stages: list[AssistantPipelineStage]
    audio: bytes
    text: str
    sample_rate: int
    num_channels: int
    stt_provider: AssistantSTTName
    llm_provider: AssistantLLMName
    tts_provider: AssistantTTSName
    llm_model: str
    system_prompt: str | None
    enable_tools: bool
    vosk_model_id: str = ''
    piper_voice_id: str = ''
    kokoro_voice_id: str = ''


class AssistantState(Immutable):
    """State for the assistant service."""

    is_listening: bool = False
    is_microphone_mute: bool = True
    is_active: bool = field(
        default=read_from_persistent_store(
            'assistant:is_active',
            default=False,
        ),
    )
    selected_stt: AssistantSTTName = field(
        default=read_from_persistent_store(
            'assistant:selected_stt',
            default=AssistantSTTName.VOSK,
            mapper=lambda value: AssistantSTTName(value)
            if value in AssistantSTTName.__members__.values()
            else AssistantSTTName.VOSK,
        ),
    )
    selected_llm: AssistantLLMName = field(
        default=read_from_persistent_store(
            'assistant:selected_llm',
            default=AssistantLLMName.OLLAMA,
            mapper=lambda value: AssistantLLMName(value)
            if value in AssistantLLMName.__members__.values()
            else AssistantLLMName.OLLAMA,
        ),
    )
    selected_models: dict[AssistantLLMName, str] = field(
        default_factory=lambda: read_from_persistent_store(
            'assistant:selected_llm_model',
            default=DEFAULT_MODELS,
            mapper=_load_selected_models,
        ),
    )
    # Named generic LLM providers added by the user (or auto-registered by
    # services like the Hermes Docker composition). Credentials live in the
    # secrets file under per-provider keys; this slice only tracks identity.
    generic_llm_providers: tuple[GenericLLMProvider, ...] = field(
        default_factory=lambda: read_from_persistent_store(
            'assistant:generic_llm_providers',
            default=(),
            mapper=_load_generic_llm_providers,
        ),
    )
    # The provider id whose credentials are currently copied into the
    # canonical generic-LLM secret keys. Empty = none selected.
    selected_generic_llm_provider: str = field(
        default=read_from_persistent_store(
            'assistant:selected_generic_llm_provider',
            default='',
        ),
    )
    # Cached `ollama.Client.show(model).capabilities` per model id. Populated
    # lazily after a model is downloaded or selected. Empty tuple means "probe
    # failed / N/A".
    ollama_model_capabilities: dict[str, tuple[str, ...]] = field(
        default_factory=dict,
    )
    # Cached set of locally-downloaded Ollama model tags, stored **normalised**
    # (lowercase + explicit ``:tag``). Populated by
    # ``OllamaEngine.refresh_downloaded_models()`` — never read by calling
    # ``ollama.list()`` from a store dispatch path, since that would block the
    # reducer thread when the daemon is slow / down.
    ollama_downloaded_models: tuple[str, ...] = field(default_factory=tuple)
    # Becomes True after the first ``refresh_downloaded_models`` completes
    # (success or daemon-down). While False, ``is_setup`` is optimistic and
    # trusts the user's selected model rather than reporting "not set up" for
    # the duration of the first daemon round-trip on every cold boot. Not
    # persisted — process-local truth.
    ollama_downloaded_models_refreshed: bool = False
    # Per-Ollama-model thinking flag. Persisted across restarts; only meaningful
    # for models whose capability set includes ``'thinking'``.
    ollama_thinking_enabled: dict[str, bool] = field(
        default_factory=lambda: read_from_persistent_store(
            'assistant:ollama_thinking_enabled',
            default={},
            mapper=_load_ollama_thinking_enabled,
        ),
    )
    selected_tts: AssistantTTSName = field(
        default=read_from_persistent_store(
            'assistant:selected_tts',
            default=AssistantTTSName.PIPER,
            mapper=lambda value: AssistantTTSName(value)
            if value in AssistantTTSName.__members__.values()
            else AssistantTTSName.PIPER,
        ),
    )
    # Currently selected Piper voice id (HuggingFace path without
    # extension). Backs both the assistant subprocess TTS and the
    # standalone speech-synthesis service.
    selected_piper_voice: str = field(
        default=read_from_persistent_store(
            'assistant:selected_piper_voice',
            default=DEFAULT_PIPER_VOICE_ID,
            mapper=_load_piper_voice,
        ),
    )
    # Cached set of locally-downloaded Piper voice ids. Process-local;
    # refreshed by ``PiperEngine.refresh_downloaded_voices()``.
    piper_downloaded_voices: tuple[str, ...] = field(default_factory=tuple)
    # Currently selected Kokoro voice id (e.g. ``af_heart``). Kokoro
    # bundles every voice in a single on-disk file pair, so this is
    # purely a "which key to ask kokoro-onnx for" — switching voices
    # never touches the filesystem after the initial download.
    selected_kokoro_voice: str = field(
        default=read_from_persistent_store(
            'assistant:selected_kokoro_voice',
            default=DEFAULT_KOKORO_VOICE_ID,
            mapper=_load_kokoro_voice,
        ),
    )
    # True once both ``kokoro-v1.0.onnx`` and ``voices-v1.0.bin`` exist
    # on disk. Process-local; refreshed by
    # ``KokoroEngine.refresh_downloaded_state()`` on service start and
    # after a successful download. Single boolean is enough because the
    # bundle is all-or-nothing — unlike Piper there are no per-voice
    # files to track.
    kokoro_is_downloaded: bool = False
    # Currently selected Vosk STT model id (alphacephei model id, e.g.
    # ``vosk-model-small-en-us-0.15``). Backs both the speech-recognition
    # service and the assistant subprocess STT.
    selected_vosk_model: str = field(
        default=read_from_persistent_store(
            'assistant:selected_vosk_model',
            default=DEFAULT_VOSK_MODEL_ID,
            mapper=_load_vosk_model,
        ),
    )
    # Cached set of locally-downloaded Vosk model ids. Process-local;
    # refreshed by ``VoskEngine.refresh_downloaded_models()``.
    vosk_downloaded_models: tuple[str, ...] = field(default_factory=tuple)
    selected_image_generator: AssistantImageGeneratorName = field(
        default=read_from_persistent_store(
            'assistant:selected_image_generator',
            default=AssistantImageGeneratorName.GOOGLE,
            mapper=lambda value: AssistantImageGeneratorName(value)
            if value in AssistantImageGeneratorName.__members__.values()
            else AssistantImageGeneratorName.GOOGLE,
        ),
    )
    mcp_servers: dict[str, McpServerMetadata] = field(default_factory=dict)
    enabled_mcp_servers: list[str] = field(
        default_factory=lambda: read_from_persistent_store(
            'assistant:enabled_mcp_servers',
            default=[],
            mapper=lambda value: json.loads(value)
            if isinstance(value, str)
            else list(value),
        ),
    )
    # Enabled servers with full metadata for gRPC autorun (wrapped for gRPC)
    enabled_mcp_servers_with_metadata: EnabledMcpServersWithMetadata = field(
        default_factory=EnabledMcpServersWithMetadata,
    )
    # Setup status for all provider engines - source of truth for UI
    provider_setup_status: dict[str, bool] = field(default_factory=dict)
    # Trigger source / policy carried during the active listening session.
    active_source: AssistantTriggerSourceUnion | None = None
    active_policy: AssistantTriggerPolicy | None = None
    # Mic the active listening session consumes audio from (empty = system mic).
    active_audio_source: str = ''
    last_stop_reason: AssistantStopReasonUnion | None = None
    policies: tuple[AssistantTriggerPolicyEntry, ...] = field(
        default_factory=_default_policies,
    )
