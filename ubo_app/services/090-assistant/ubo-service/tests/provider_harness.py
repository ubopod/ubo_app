"""Shared harness for the provider end-to-end (`providers`-marked) tests.

These tests drive the real one-shot pipeline API (`_run_request`) in this
subprocess venv with a fake RPC client and REAL provider credentials read from
the user's ubo secrets file. They validate that TTS / STT / LLM providers and
the pipeline work end-to-end, independently of the screen-reader / core / gRPC
layers. They hit real cloud APIs (network + cost) and are skipped per-provider
when a credential or local model is missing.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar
from uuid import uuid4

import betterproto
from dotenv import dotenv_values
from ubo_bindings.ubo.v1 import (
    AssistanceAudioFrame,
    AssistanceErrorFrame,
    AssistanceTextFrame,
    AssistantLlmName,
    AssistantPipelineStage,
    AssistantRunPipelineEvent,
    AssistantSttName,
    AssistantTtsName,
)

from ubo_assistant.constants import DATA_PATH
from ubo_assistant.kokoro import MODEL_PATH as KOKORO_MODEL_PATH
from ubo_assistant.kokoro import VOICES_PATH as KOKORO_VOICES_PATH
from ubo_assistant.piper import DEFAULT_PIPER_VOICE_ID
from ubo_assistant.request_handler import _run_request
from ubo_assistant.vosk import DEFAULT_VOSK_MODEL_ID

if TYPE_CHECKING:
    from ubo_bindings.ubo.v1 import Action

_EnumT = TypeVar('_EnumT', bound=betterproto.Enum)

# ---------------------------------------------------------------------------
# Secrets + the env-var indirection request_providers._secret relies on.
# ---------------------------------------------------------------------------

# request_providers._secret does ``os.environ.get('<NAME>_SECRET_ID')`` to learn
# the secret id, then ``client.query_secret(<id>)``. Production exports these via
# ``services/090-assistant/ubo_handle.binary_env_provider``; tests aren't
# launched that way, so the conftest autouse fixture exports this map. Values are
# the secret ids (= keys in the user's ``.secrets.env``); mirrors
# ``ubo_app.constants.assistant``.
SECRET_ID_ENV: dict[str, str] = {
    'OPENAI_API_KEY_SECRET_ID': 'openai_api_key',
    'ANTHROPIC_API_KEY_SECRET_ID': 'anthropic_api_key',
    'GROK_API_KEY_SECRET_ID': 'grok_api_key',
    'CEREBRAS_API_KEY_SECRET_ID': 'cerebras_api_key',
    'QWEN_API_KEY_SECRET_ID': 'qwen_api_key',
    'DEEPSEEK_API_KEY_SECRET_ID': 'deepseek_api_key',
    'OPENROUTER_API_KEY_SECRET_ID': 'openrouter_api_key',
    'MISTRAL_API_KEY_SECRET_ID': 'mistral_api_key',
    'VENICE_API_KEY_SECRET_ID': 'venice_api_key',
    'DEEPGRAM_API_KEY_SECRET_ID': 'deepgram_api_key',
    'ASSEMBLYAI_API_KEY_SECRET_ID': 'assemblyai_api_key',
    'ELEVENLABS_API_KEY_SECRET_ID': 'elevenlabs_api_key',
    'ELEVENLABS_VOICE_ID': 'elevenlabs_voice_id',
    'RIME_API_KEY_SECRET_ID': 'rime_api_key',
    'GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID': 'google_cloud_service_account_key',
    'GOOGLE_API_KEY_SECRET_ID': 'google_api_key',
    'OLLAMA_ONPREM_URL_SECRET_ID': 'ollama_onprem_url',
    'GENERIC_LLM_BASE_URL_SECRET_ID': 'generic_llm_base_url',
    'GENERIC_LLM_API_KEY_SECRET_ID': 'generic_llm_api_key',
    'GENERIC_LLM_MODEL_SECRET_ID': 'generic_llm_model',
}


def _secrets_path() -> Path:
    override = os.environ.get('UBO_SECRETS_PATH')
    return Path(override) if override else DATA_PATH / '.secrets.env'


@lru_cache(maxsize=1)
def load_secrets() -> dict[str, str]:
    """Read the user's ubo secrets (``.secrets.env``); empty if absent."""
    path = _secrets_path()
    if not path.exists():
        return {}
    return {key: value for key, value in dotenv_values(path).items() if value}


# ---------------------------------------------------------------------------
# Fake RPC client + output draining.
# ---------------------------------------------------------------------------


class FakeUboRPCClient:
    """Minimal stand-in for ``UboRPCClient`` used to drive ``_run_request``.

    ``query_secret`` returns real keys from the user's secrets; ``dispatch``
    captures the report actions the collector emits so tests can read the
    produced audio / text / errors back.
    """

    def __init__(self) -> None:
        """Start with an empty capture buffer and the loaded secrets."""
        self.frames: list[Action] = []
        self._secrets = load_secrets()

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        """The running loop (the collector timestamps/creates tasks against it)."""
        return asyncio.get_running_loop()

    async def query_secret(
        self,
        key: str,
        *,
        covered: bool = False,
        default: str | None = None,
    ) -> str | None:
        """Return the real secret value for *key* from the user's secrets."""
        _ = covered
        return self._secrets.get(key, default)

    def dispatch(self, *, action: Action) -> None:
        """Capture a dispatched action for later draining."""
        self.frames.append(action)

    def subscribe_event(self, *_args: object, **_kwargs: object) -> object:
        """No-op subscription (the one-shot path doesn't need events)."""
        return lambda: None


@dataclass
class PipelineResult:
    """Drained output of a one-shot pipeline run."""

    audio: bytes = b''
    rate: int = 0
    text: str = ''
    errors: list[str] = field(default_factory=list)


def _drain(actions: list[Action]) -> PipelineResult:
    result = PipelineResult()
    audio = bytearray()
    text_parts: list[str] = []
    for action in actions:
        # The collector only ever dispatches AssistantReportActions here.
        _, frame = betterproto.which_one_of(
            action.assistant_report_action.data,
            'acceptable_assistance_frame',
        )
        # ``isinstance`` narrows the which_one_of result to the concrete frame.
        if isinstance(frame, AssistanceAudioFrame) and frame.audio:
            audio += frame.audio.data
            result.rate = frame.audio.rate
        elif isinstance(frame, AssistanceTextFrame):
            text_parts.append(frame.text)
        elif isinstance(frame, AssistanceErrorFrame):
            result.errors.append(frame.error)
    result.audio = bytes(audio)
    result.text = ''.join(text_parts)
    return result


async def run_pipeline(
    client: FakeUboRPCClient,
    *,
    stages: list[AssistantPipelineStage],
    text: str = '',
    audio: bytes = b'',
    sample_rate: int = 16000,
    num_channels: int = 1,
    stt_provider: AssistantSttName = AssistantSttName.VOSK,
    llm_provider: AssistantLlmName = AssistantLlmName.OPENAI,
    tts_provider: AssistantTtsName = AssistantTtsName.PIPER,
    llm_model: str = '',
    system_prompt: str | None = None,
    vosk_model_id: str | None = None,
    piper_voice_id: str | None = None,
    kokoro_voice_id: str | None = None,
) -> PipelineResult:
    """Run a single one-shot pipeline via the real ``_run_request`` and drain it."""
    client.frames.clear()
    event = AssistantRunPipelineEvent(
        session_id=uuid4().hex,
        stages=list(stages),
        text=text,
        audio=audio,
        sample_rate=sample_rate,
        num_channels=num_channels,
        stt_provider=stt_provider,
        llm_provider=llm_provider,
        tts_provider=tts_provider,
        llm_model=llm_model,
        system_prompt=system_prompt,
        vosk_model_id=vosk_model_id,
        piper_voice_id=piper_voice_id,
        kokoro_voice_id=kokoro_voice_id,
    )
    await _run_request(client, event)  # type: ignore[arg-type]
    return _drain(client.frames)


async def resample_pcm(audio: bytes, in_rate: int, out_rate: int) -> bytes:
    """Resample 16-bit mono PCM using the same resampler the pipeline uses."""
    if in_rate == out_rate or not audio:
        return audio
    from pipecat.audio.utils import create_stream_resampler

    return await create_stream_resampler().resample(audio, in_rate, out_rate)


# ---------------------------------------------------------------------------
# Round-trip phrase + lenient keyword matching (TTS+STT is lossy).
# ---------------------------------------------------------------------------

PHRASE = 'the quick brown fox jumps over the lazy dog'


def content_words(phrase: str) -> set[str]:
    """Return the distinct lowercase alphabetic words of *phrase*."""
    return set(re.findall(r'[a-z]+', phrase.lower()))


def keyword_hit_ratio(transcript: str, phrase: str) -> float:
    """Fraction of *phrase*'s distinct words that appear in *transcript*."""
    words = content_words(phrase)
    if not words:
        return 0.0
    lowered = transcript.lower()
    return sum(word in lowered for word in words) / len(words)


# ---------------------------------------------------------------------------
# Provider tables.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provider(Generic[_EnumT]):
    """A provider under test: its enum, required secrets and/or local models."""

    id: str
    enum: _EnumT
    secret_ids: tuple[str, ...] = ()
    local_paths: tuple[Path, ...] = ()
    model: str = ''

    def available(self) -> bool:
        """Report whether every required secret and local model is present."""
        secrets = load_secrets()
        if not all(secrets.get(secret_id) for secret_id in self.secret_ids):
            return False
        return all(path.exists() for path in self.local_paths)


_VOSK_PATH = DATA_PATH / DEFAULT_VOSK_MODEL_ID
_PIPER_PATH = (DATA_PATH / DEFAULT_PIPER_VOICE_ID).with_suffix('.onnx')

TTS_PROVIDERS: tuple[Provider[AssistantTtsName], ...] = (
    Provider('piper', AssistantTtsName.PIPER, local_paths=(_PIPER_PATH,)),
    Provider(
        'kokoro',
        AssistantTtsName.KOKORO,
        local_paths=(KOKORO_MODEL_PATH, KOKORO_VOICES_PATH),
    ),
    Provider(
        'google',
        AssistantTtsName.GOOGLE,
        secret_ids=('google_cloud_service_account_key',),
    ),
    Provider('openai', AssistantTtsName.OPENAI, secret_ids=('openai_api_key',)),
    Provider(
        'elevenlabs',
        AssistantTtsName.ELEVENLABS,
        secret_ids=('elevenlabs_api_key', 'elevenlabs_voice_id'),
    ),
    Provider('rime', AssistantTtsName.RIME, secret_ids=('rime_api_key',)),
    Provider('venice', AssistantTtsName.VENICE, secret_ids=('venice_api_key',)),
    Provider(
        'deepgram',
        AssistantTtsName.DEEPGRAM,
        secret_ids=('deepgram_api_key',),
    ),
)

STT_PROVIDERS: tuple[Provider[AssistantSttName], ...] = (
    Provider('vosk', AssistantSttName.VOSK, local_paths=(_VOSK_PATH,)),
    Provider(
        'google',
        AssistantSttName.GOOGLE,
        secret_ids=('google_cloud_service_account_key',),
    ),
    Provider(
        'google_segmented',
        AssistantSttName.GOOGLE_SEGMENTED,
        secret_ids=('google_cloud_service_account_key',),
    ),
    Provider('openai', AssistantSttName.OPENAI, secret_ids=('openai_api_key',)),
    Provider('deepgram', AssistantSttName.DEEPGRAM, secret_ids=('deepgram_api_key',)),
    Provider(
        'assemblyai',
        AssistantSttName.ASSEMBLYAI,
        secret_ids=('assemblyai_api_key',),
    ),
    Provider('venice', AssistantSttName.VENICE, secret_ids=('venice_api_key',)),
)

# Cheap/fast models per provider (mirroring the app's DEFAULT_MODELS where they
# match the account). Model ids may need occasional updates; a wrong id surfaces
# as a test failure (informative). Local `ollama` is deferred to phase 2;
# `ollama_onprem` resolves its model at runtime (see test_provider_llm). The
# `generic_llm` provider is intentionally excluded: it points at the user's own
# arbitrary OpenAI-compatible endpoint, so there's no portable model to assert.
LLM_PROVIDERS: tuple[Provider[AssistantLlmName], ...] = (
    Provider(
        'openai',
        AssistantLlmName.OPENAI,
        secret_ids=('openai_api_key',),
        model='gpt-4o-mini',
    ),
    Provider(
        'anthropic',
        AssistantLlmName.ANTHROPIC,
        secret_ids=('anthropic_api_key',),
        model='claude-sonnet-4-5',
    ),
    Provider(
        'grok',
        AssistantLlmName.GROK,
        secret_ids=('grok_api_key',),
        model='grok-4-0709',
    ),
    Provider(
        'cerebras',
        AssistantLlmName.CEREBRAS,
        secret_ids=('cerebras_api_key',),
        model='gpt-oss-120b',
    ),
    Provider(
        'qwen',
        AssistantLlmName.QWEN,
        secret_ids=('qwen_api_key',),
        model='qwen-turbo',
    ),
    Provider(
        'deepseek',
        AssistantLlmName.DEEPSEEK,
        secret_ids=('deepseek_api_key',),
        model='deepseek-chat',
    ),
    Provider(
        'openrouter',
        AssistantLlmName.OPENROUTER,
        secret_ids=('openrouter_api_key',),
        model='openai/gpt-4o-mini',
    ),
    Provider(
        'mistral',
        AssistantLlmName.MISTRAL,
        secret_ids=('mistral_api_key',),
        model='mistral-small-latest',
    ),
    Provider(
        'venice',
        AssistantLlmName.VENICE,
        secret_ids=('venice_api_key',),
        model='llama-3.3-70b',
    ),
    Provider(
        'google_vertex',
        AssistantLlmName.GOOGLE,
        secret_ids=('google_cloud_service_account_key',),
        model='gemini-2.0-flash',
    ),
    Provider(
        'ollama_onprem',
        AssistantLlmName.OLLAMA_ONPREM,
        secret_ids=('ollama_onprem_url',),
    ),
)
