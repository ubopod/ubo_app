"""Credential contract tests for the API-key-backed assistant engines.

These engines are thin adapters whose only real logic is API-key handling:
``is_setup`` validates a stored key against the provider's regex, ``_setup``
persists the key entered through ``ubo_input``, and ``_clear_credentials``
forgets it. A wrong pattern silently and permanently marks an engine as "not
set up", so the accept/reject contract is worth pinning per provider.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ubo_app.constants.assistant import (
    ELEVENLABS_API_KEY_SECRET_ID,
    ELEVENLABS_VOICE_ID,
)
from ubo_app.engines import (
    anthropic,
    assemblyai,
    cerebras,
    deepgram,
    deepseek,
    elevenlabs,
    google,
    grok,
    mistral,
    openai,
    openrouter,
    qwen,
    rime,
    venice,
)
from ubo_app.store.input.types import InputMethod, InputResult
from ubo_app.utils import secrets

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from redux import BaseAction

    from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin


class _FakeStore:
    def dispatch(self, *_actions: BaseAction) -> None: ...


# (engine module, engine class, a well-formed key, extra secrets needed by
# ``is_setup``). The secret id under test is the engine's first declared
# ``credential_secret_ids`` entry, so it never drifts from the source.
_ENGINES = [
    pytest.param(anthropic, anthropic.AnthropicEngine, 'sk-ant-' + 'a' * 40, {},
                 id='anthropic'),
    pytest.param(openai, openai.OpenAIEngine, 'sk-' + 'a' * 32, {}, id='openai'),
    pytest.param(cerebras, cerebras.CerebrasEngine, 'csk-' + 'a' * 40, {},
                 id='cerebras'),
    pytest.param(deepseek, deepseek.DeepSeekEngine, 'sk-' + 'a' * 32, {},
                 id='deepseek'),
    pytest.param(venice, venice.VeniceEngine, 'a' * 20, {}, id='venice'),
    pytest.param(grok, grok.GrokEngine, 'xai-' + 'a' * 80, {}, id='grok'),
    pytest.param(qwen, qwen.QwenEngine, 'sk-' + 'a' * 32, {}, id='qwen'),
    pytest.param(openrouter, openrouter.OpenRouterEngine, 'sk-or-v1-' + 'a' * 64, {},
                 id='openrouter'),
    pytest.param(mistral, mistral.MistralEngine, 'a' * 32, {}, id='mistral'),
    pytest.param(deepgram, deepgram.DeepgramEngine, 'a' * 40, {}, id='deepgram'),
    pytest.param(assemblyai, assemblyai.AssemblyAIEngine, 'a' * 32, {},
                 id='assemblyai'),
    pytest.param(rime, rime.RimeEngine, 'a' * 32, {}, id='rime'),
    # No ``extra``: the API key alone is the whole setup requirement — the voice
    # id is optional (TTS falls back to the default voice, STT needs no voice).
    pytest.param(elevenlabs, elevenlabs.ElevenLabsEngine, 'a' * 32, {},
                 id='elevenlabs'),
    pytest.param(google, google.GoogleEngine, 'AIza' + 'a' * 35, {}, id='google'),
]


@pytest.fixture
def _tmp_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect the secrets file to a throwaway path for the whole test."""
    secrets_path = tmp_path / '.secrets.env'
    secrets_path.write_text('')
    monkeypatch.setattr(secrets, 'SECRETS_PATH', secrets_path)


@pytest.mark.usefixtures('_tmp_secrets')
@pytest.mark.parametrize(('module', 'engine_cls', 'valid_key', 'extra'), _ENGINES)
def test_is_setup_accepts_valid_key_and_rejects_malformed(
    module: ModuleType,  # noqa: ARG001
    engine_cls: type[NeedsSetupMixin],
    valid_key: str,
    extra: dict[str, str],
) -> None:
    """``is_setup`` is True only for a well-formed stored key."""
    engine = engine_cls()
    secret_id = engine.credential_secret_ids[0]

    assert engine.is_setup is False  # no key stored yet

    for key, value in extra.items():
        secrets.write_secret(key=key, value=value)
    secrets.write_secret(key=secret_id, value=valid_key)
    assert engine.is_setup is True

    secrets.write_secret(key=secret_id, value='!!!not-a-key!!!')
    assert engine.is_setup is False


@pytest.mark.usefixtures('_tmp_secrets')
@pytest.mark.parametrize(('module', 'engine_cls', 'valid_key', 'extra'), _ENGINES)
def test_clear_credentials_forgets_the_key(
    module: ModuleType,  # noqa: ARG001
    engine_cls: type[NeedsSetupMixin],
    valid_key: str,
    extra: dict[str, str],
) -> None:
    """``_clear_credentials`` removes the stored key."""
    engine = engine_cls()
    secret_id = engine.credential_secret_ids[0]
    for key, value in extra.items():
        secrets.write_secret(key=key, value=value)
    secrets.write_secret(key=secret_id, value=valid_key)

    engine._clear_credentials()  # noqa: SLF001

    assert secrets.read_secret(secret_id) is None
    assert engine.is_setup is False


@pytest.mark.usefixtures('_tmp_secrets')
@pytest.mark.parametrize(('module', 'engine_cls', 'valid_key', 'extra'), _ENGINES)
async def test_setup_persists_the_entered_key(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    engine_cls: type[NeedsSetupMixin],
    valid_key: str,
    extra: dict[str, str],  # noqa: ARG001
) -> None:
    """``_setup`` writes the key returned by ``ubo_input`` to the secrets file."""
    async def fake_ubo_input(*_args: object, **_kwargs: object) -> object:
        return '', InputResult(
            data={'api_key': valid_key, 'voice_id': 'a' * 20},
            files={},
            method=InputMethod.WEB_DASHBOARD,
        )

    monkeypatch.setattr(module, 'ubo_input', fake_ubo_input)
    monkeypatch.setattr(module, 'store', _FakeStore(), raising=False)

    engine = engine_cls()
    await engine._setup()  # noqa: SLF001

    assert secrets.read_secret(engine.credential_secret_ids[0]) == valid_key


@pytest.mark.parametrize(('module', 'engine_cls', 'valid_key', 'extra'), _ENGINES)
def test_engine_exposes_stable_identity(
    module: ModuleType,  # noqa: ARG001
    engine_cls: type[NeedsSetupMixin],
    valid_key: str,  # noqa: ARG001
    extra: dict[str, str],  # noqa: ARG001
) -> None:
    """Name, label, and not-setup message are non-empty strings."""
    engine = engine_cls()

    for value in (engine.name, engine.label, engine.not_setup_message):
        assert isinstance(value, str)
        assert value


@pytest.mark.usefixtures('_tmp_secrets')
def test_elevenlabs_is_setup_without_a_voice_id() -> None:
    """An API key alone sets ElevenLabs up — the voice id is TTS-only.

    Gating ``is_setup`` on the voice id would hide ElevenLabs from the
    speech-to-text picker, which never needs a voice.
    """
    engine = elevenlabs.ElevenLabsEngine()
    secrets.write_secret(key=ELEVENLABS_API_KEY_SECRET_ID, value='a' * 32)

    assert secrets.read_secret(ELEVENLABS_VOICE_ID) is None
    assert engine.is_setup is True


@pytest.mark.usefixtures('_tmp_secrets')
async def test_elevenlabs_setup_without_voice_keeps_the_stored_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running setup and skipping the voice must not wipe an existing one."""
    secrets.write_secret(key=ELEVENLABS_VOICE_ID, value='b' * 20)

    async def fake_ubo_input(*_args: object, **_kwargs: object) -> object:
        return '', InputResult(
            data={'api_key': 'a' * 32, 'voice_id': ''},
            files={},
            method=InputMethod.WEB_DASHBOARD,
        )

    monkeypatch.setattr(elevenlabs, 'ubo_input', fake_ubo_input)
    monkeypatch.setattr(elevenlabs, 'store', _FakeStore(), raising=False)

    await elevenlabs.ElevenLabsEngine()._setup()  # noqa: SLF001

    assert secrets.read_secret(ELEVENLABS_API_KEY_SECRET_ID) == 'a' * 32
    assert secrets.read_secret(ELEVENLABS_VOICE_ID) == 'b' * 20
