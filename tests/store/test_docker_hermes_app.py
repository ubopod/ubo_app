"""Tests for the Hermes Docker composition app."""

from __future__ import annotations

import asyncio
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import dotenv

from ubo_app.constants.assistant import (
    OPENAI_API_KEY_SECRET_ID,
    OPENROUTER_API_KEY_SECRET_ID,
)
from ubo_app.utils import secrets

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest
    from redux import BaseAction

    from ubo_app.store.input.types import WebUIInputDescription

    # Type-only: used solely to annotate the name-filtered actions below. Kept
    # out of runtime imports so the dispatched action's class identity is never
    # compared (see the class-name matching note in the tests).
    from ubo_app.store.services.assistant import (
        AssistantAddGenericLLMProviderAction,
        AssistantRemoveGenericLLMProviderAction,
    )


DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'

# Stand-in mirroring the *current* upstream compose so prepare_hermes never
# touches the network in tests. Faithful to the real three-container layout:
# agent + dashboard both carry HERMES_HOME=/home/hermes/.hermes (so the
# inject-once logic is exercised), hermes-home is shared at two container
# paths, hermes-agent-src is the disposable source volume, and the workspace
# bind uses the ${HERMES_WORKSPACE:-${HOME}/workspace} form.
UPSTREAM_COMPOSE = """services:
  hermes-agent:
    image: nousresearch/hermes-agent:latest
    volumes:
      - hermes-home:/home/hermes/.hermes
      - hermes-agent-src:/opt/hermes
    environment:
      - HERMES_HOME=/home/hermes/.hermes
  hermes-dashboard:
    image: nousresearch/hermes-agent:latest
    volumes:
      - hermes-home:/home/hermes/.hermes
    environment:
      - HERMES_HOME=/home/hermes/.hermes
  hermes-webui:
    image: ghcr.io/nesquena/hermes-webui:latest
    volumes:
      - hermes-home:/home/hermeswebui/.hermes
      - hermes-agent-src:/home/hermeswebui/.hermes/hermes-agent:ro
      - ${HERMES_WORKSPACE:-${HOME}/workspace}:/workspace
volumes:
  hermes-home:
  hermes-agent-src:
"""


class SecretsModule(Protocol):
    """Protocol for the secrets module attributes patched by these tests."""

    SECRETS_PATH: Path


class _FakeStore:
    def __init__(self) -> None:
        self.dispatched: list[BaseAction] = []

    def dispatch(self, *actions: BaseAction) -> None:
        self.dispatched.extend(actions)


class ContainerEntryProtocol(Protocol):
    """Subset of ContainerEntry fields asserted by these tests."""

    secret_keys: tuple[str, ...]
    cleanup: object


class HermesOAuthProviderProtocol(Protocol):
    """Subset of the OAuth provider tuple asserted by these tests."""

    id: str
    label: str
    needs_code: bool


class HermesModule(Protocol):
    """Protocol for the Hermes module members used by these tests."""

    COMPOSITIONS_PATH: Path
    HERMES_DATA_PATH: Path
    HERMES_API_SERVER_KEY_SECRET: str
    HERMES_LLM_PROVIDER_SECRET_KEYS: tuple[str, str, str]
    HERMES_DASHBOARD_AUTH_SECRET_KEYS: tuple[str, str, str]
    HERMES_DASHBOARD_USERNAME_SECRET: str
    HERMES_DASHBOARD_PASSWORD_SECRET: str
    HERMES_DASHBOARD_SESSION_SECRET: str
    HERMES_OAUTH_PROVIDERS: tuple[HermesOAuthProviderProtocol, ...]
    ENTRY: ContainerEntryProtocol
    secrets: SecretsModule
    store: _FakeStore

    async def prepare_hermes(self) -> bool:
        """Prepare Hermes composition files."""
        ...

    async def configure_dashboard_auth(self) -> bool:
        """Prompt for the dashboard sign-in credentials."""
        ...

    def extract_oauth_prompt(
        self,
        output: str,
        *,
        expect_device_code: bool = True,
    ) -> tuple[str | None, str | None]:
        """Parse the verification URL and device code out of CLI output."""
        ...

    async def _read_oauth_prompt(
        self,
        process: object,
        provider: HermesOAuthProviderProtocol,
        transcript: list[str],
    ) -> tuple[str | None, str | None]:
        """Stream stdout until the URL and any device code have appeared."""
        ...

    def _cleanup_hermes(self) -> None: ...


def _import_hermes() -> HermesModule:
    """Import the Hermes module as the Docker service would."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)

    try:
        return cast('HermesModule', import_module('apps.hermes'))
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


def _use_temp_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hermes: HermesModule,
) -> None:
    fake_path = tmp_path / '.secrets.env'
    fake_path.write_text('')
    monkeypatch.setattr(secrets, 'SECRETS_PATH', fake_path)
    monkeypatch.setattr(hermes.secrets, 'SECRETS_PATH', fake_path)


def _prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    dashboard_credentials: tuple[str, str] | None = ('ubo', 'hunter2'),
) -> tuple[HermesModule, _FakeStore]:
    hermes = _import_hermes()
    _use_temp_secrets(monkeypatch, tmp_path, hermes)
    monkeypatch.setattr(hermes, 'COMPOSITIONS_PATH', tmp_path)
    monkeypatch.setattr(hermes, 'HERMES_DATA_PATH', tmp_path / 'hermes-data')
    fake_store = _FakeStore()
    monkeypatch.setattr(hermes, 'store', fake_store)

    # Pre-seed the sign-in credentials so `prepare_hermes` takes the
    # already-configured path and never opens the web UI form.
    if dashboard_credentials is not None:
        username, password = dashboard_credentials
        secrets.write_secret(
            key=hermes.HERMES_DASHBOARD_USERNAME_SECRET,
            value=username,
        )
        secrets.write_secret(
            key=hermes.HERMES_DASHBOARD_PASSWORD_SECRET,
            value=password,
        )

    composition_path = tmp_path / 'hermes'
    composition_path.mkdir()
    (composition_path / 'docker-compose.yml').write_text(UPSTREAM_COMPOSE)

    return hermes, fake_store


async def test_prepare_hermes_writes_env_with_api_server_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The prepare phase enables the API server in the compose .env file."""
    hermes, _ = _prepare(monkeypatch, tmp_path)

    assert await hermes.prepare_hermes()

    env = (tmp_path / 'hermes' / '.env').read_text()
    assert 'API_SERVER_ENABLED=true' in env
    api_server_key = secrets.read_secret(hermes.HERMES_API_SERVER_KEY_SECRET)
    assert api_server_key
    assert f'HERMES_API_SERVER_KEY={api_server_key}' in env


async def test_prepare_hermes_converts_volumes_to_host_bind_mounts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The prepare phase decouples Hermes state from the disposable image.

    Every ``hermes-home`` mount becomes a host bind mount at a single shared
    persistent dir, the ``/workspace`` mount is redirected there too, and the
    image-derived ``hermes-agent-src`` volume is left untouched.
    """
    hermes, _ = _prepare(monkeypatch, tmp_path)

    assert await hermes.prepare_hermes()

    compose = (tmp_path / 'hermes' / 'docker-compose.yml').read_text()
    data_dir = tmp_path / 'hermes-data' / 'data'
    workspace_dir = tmp_path / 'hermes-data' / 'workspace'

    # hermes-home converted to a host bind mount at every container target,
    # preserving the (upstream-defined) container-side path.
    assert f'- {data_dir}:/home/hermes/.hermes' in compose
    assert f'- {data_dir}:/home/hermeswebui/.hermes' in compose
    assert '- hermes-home:' not in compose
    # workspace redirected to the persistent dir.
    assert f'- {workspace_dir}:/workspace' in compose
    assert '${HERMES_WORKSPACE' not in compose
    # hermes-agent-src (image-derived source) stays a named volume.
    assert '- hermes-agent-src:/opt/hermes' in compose

    # The gateway API server env vars are injected exactly once (into the agent
    # service, after its HERMES_HOME), independent of the home path value.
    assert compose.count('- API_SERVER_ENABLED=true') == 1
    assert '- API_SERVER_KEY=${HERMES_API_SERVER_KEY}' in compose
    assert '- GATEWAY_ALLOW_ALL_USERS=true' in compose

    # The persistent dirs are created, idempotently.
    assert data_dir.is_dir()
    assert workspace_dir.is_dir()


async def test_prepare_hermes_registers_assistant_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The prepare phase auto-registers a named generic LLM provider."""
    hermes, fake_store = _prepare(monkeypatch, tmp_path)

    assert await hermes.prepare_hermes()

    base_url_key, api_key_key, model_key = hermes.HERMES_LLM_PROVIDER_SECRET_KEYS
    assert secrets.read_secret(base_url_key) == 'http://127.0.0.1:8642/v1'
    assert secrets.read_secret(api_key_key) == secrets.read_secret(
        hermes.HERMES_API_SERVER_KEY_SECRET,
    )
    assert secrets.read_secret(model_key) == 'hermes-agent'

    # Match by class name, not isinstance: across the full unit suite the
    # assistant action module can be re-imported under a different generation,
    # so the dispatched action's class is not identity-equal to a top-level
    # import (see the sys.modules isolation note in MEMORY.md).
    add_actions = cast(
        'list[AssistantAddGenericLLMProviderAction]',
        [
            action
            for action in fake_store.dispatched
            if type(action).__name__ == 'AssistantAddGenericLLMProviderAction'
        ],
    )
    assert len(add_actions) == 1
    assert add_actions[0].provider_id == 'hermes'
    assert add_actions[0].label == 'Hermes'


async def test_prepare_hermes_writes_dashboard_auth_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The prepare phase registers a basic-auth provider for the dashboard.

    The dashboard container always binds ``0.0.0.0`` internally, so the auth
    gate engages in loopback mode too — the credentials must be written
    regardless of the LAN toggle.
    """
    hermes, _ = _prepare(monkeypatch, tmp_path)

    assert await hermes.prepare_hermes()

    override = (tmp_path / 'hermes' / 'docker-compose.override.yml').read_text()
    assert '  hermes-dashboard:\n' in override
    assert '"HERMES_DASHBOARD_BASIC_AUTH_USERNAME=ubo"' in override
    assert '"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=hunter2"' in override
    # A stable signing key is generated and persisted so dashboard sessions
    # survive a container restart.
    session_secret = secrets.read_secret(hermes.HERMES_DASHBOARD_SESSION_SECRET)
    assert session_secret
    assert f'"HERMES_DASHBOARD_BASIC_AUTH_SECRET={session_secret}"' in override


async def test_dashboard_password_survives_compose_interpolation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A password with compose/YAML metacharacters is written back verbatim.

    ``$`` is doubled so Compose interpolation leaves it alone, and the entry is
    quoted so ``"``/``#``/``:`` cannot break the YAML document.
    """
    hermes, _ = _prepare(
        monkeypatch,
        tmp_path,
        dashboard_credentials=('ubo', 'a$b"c#d:e'),
    )

    assert await hermes.prepare_hermes()

    override = (tmp_path / 'hermes' / 'docker-compose.override.yml').read_text()
    assert 'HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=a$$b\\"c#d:e' in override


class _FakeInputResult:
    """Stand-in for the ``ubo_input`` result object."""

    def __init__(self, data: dict[str, str]) -> None:
        self.data = data


def _first_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    form_data: dict[str, str] | None,
) -> HermesModule:
    """Drive prepare down its first-install path with a canned key-share form.

    ``form_data=None`` stands for a declined/cancelled form.
    """
    hermes, _ = _prepare(monkeypatch, tmp_path, dashboard_credentials=None)

    async def _accept_credentials() -> bool:
        secrets.write_secret(
            key=hermes.HERMES_DASHBOARD_USERNAME_SECRET,
            value='ubo',
        )
        secrets.write_secret(
            key=hermes.HERMES_DASHBOARD_PASSWORD_SECRET,
            value='hunter2',
        )
        return True

    monkeypatch.setattr(hermes, 'configure_dashboard_auth', _accept_credentials)

    async def _fake_input(**_: object) -> tuple[None, _FakeInputResult | None]:
        return None, None if form_data is None else _FakeInputResult(form_data)

    monkeypatch.setattr(hermes, 'ubo_input', _fake_input)
    return hermes


async def test_prepare_hermes_shares_only_the_ticked_api_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ticked keys reach Hermes' own .env under its env var names; others don't."""
    hermes = _first_run(
        monkeypatch,
        tmp_path,
        form_data={'OPENROUTER_API_KEY': 'on'},
    )
    secrets.write_secret(key=OPENROUTER_API_KEY_SECRET_ID, value='sk-or-v1-abc')
    secrets.write_secret(key=OPENAI_API_KEY_SECRET_ID, value='sk-openai-abc')

    assert await hermes.prepare_hermes()

    dotenv_path = tmp_path / 'hermes-data' / 'data' / '.env'
    assert dotenv.get_key(dotenv_path, 'OPENROUTER_API_KEY') == 'sk-or-v1-abc'
    # Configured in ubo but left unticked — sharing is per-key and opt-in.
    assert dotenv.get_key(dotenv_path, 'OPENAI_API_KEY') is None
    # Credentials are never left world-readable.
    assert dotenv_path.stat().st_mode & 0o077 == 0


async def test_key_share_options_show_a_masked_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Each option carries the key's last 4 chars, so two keys are tellable apart."""
    hermes = _first_run(monkeypatch, tmp_path, form_data={})
    secrets.write_secret(key=OPENROUTER_API_KEY_SECRET_ID, value='sk-or-v1-abcd9c2a')

    labels: list[str] = []

    async def _capturing_input(**kwargs: object) -> tuple[None, _FakeInputResult]:
        descriptions = cast('Sequence[WebUIInputDescription]', kwargs['descriptions'])
        labels.extend(field.label for field in descriptions[0].fields or [])
        return None, _FakeInputResult({})

    monkeypatch.setattr(hermes, 'ubo_input', _capturing_input)

    assert await hermes.prepare_hermes()

    assert labels == ['OpenRouter (***9c2a)']


async def test_prepare_hermes_skips_key_sharing_when_nothing_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no importable ubo secrets the form is skipped, not shown empty."""
    shown = False

    hermes = _first_run(monkeypatch, tmp_path, form_data={})

    async def _tracking_input(**_: object) -> tuple[None, _FakeInputResult]:
        nonlocal shown
        shown = True
        return None, _FakeInputResult({})

    monkeypatch.setattr(hermes, 'ubo_input', _tracking_input)

    assert await hermes.prepare_hermes()

    assert not shown
    assert not (tmp_path / 'hermes-data' / 'data' / '.env').exists()


async def test_prepare_hermes_survives_a_declined_key_share(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Sharing is optional — declining it must not fail the install."""
    hermes = _first_run(monkeypatch, tmp_path, form_data=None)
    secrets.write_secret(key=OPENROUTER_API_KEY_SECRET_ID, value='sk-or-v1-abc')

    assert await hermes.prepare_hermes()

    assert not (tmp_path / 'hermes-data' / 'data' / '.env').exists()


async def test_prepare_hermes_aborts_without_dashboard_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Declining the sign-in form aborts the prepare phase."""
    hermes, _ = _prepare(monkeypatch, tmp_path, dashboard_credentials=None)

    async def _decline() -> bool:
        return False

    monkeypatch.setattr(hermes, 'configure_dashboard_auth', _decline)

    assert not await hermes.prepare_hermes()
    assert not (tmp_path / 'hermes' / 'docker-compose.override.yml').exists()


# Captured verbatim from `hermes auth add <p> --type oauth --no-browser` on a
# device running Hermes v0.20.0. Kept exact — including the ANSI colour codes
# OpenAI Codex emits and the `Portal:` banner Nous/MiniMax print ahead of the
# real link — because those are precisely what the parser has to survive.
NOUS_OUTPUT = """Starting Hermes login via Nous Portal...
Portal: https://portal.nousresearch.com

To continue:
  1. Open: https://portal.nousresearch.com/manage-subscription?user_code=52DK-A59Z
  2. If prompted, enter code: 52DK-A59Z
Waiting for approval (polling every 1s)...
"""

CODEX_OUTPUT = (
    'To continue, follow these steps:\n'
    '\n'
    '  1. Open this URL in your browser:\n'
    '     \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n'
    '\n'
    '  2. Enter this code:\n'
    '     \x1b[94mL0JT-CIPSL\x1b[0m\n'
    '\n'
    'Waiting for sign-in... (press Ctrl+C to cancel)\n'
)

ANTHROPIC_OUTPUT = """Authorize Hermes with your Claude Pro/Max subscription.

╭─ Claude Pro/Max Authorization ────────────────────╮
│                                                   │
│  Open this link in your browser:                  │
╰───────────────────────────────────────────────────╯

  https://claude.ai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e&response_type=code&redirect_uri=https%3A%2F%2Fconsole.anthropic.com%2Foauth%2Fcode%2Fcallback&scope=org%3Acreate_api_key+user%3Aprofile+user%3Ainference&code_challenge=IUWBRloNMh_k4AWMGUvlglu9l9YBGvbg5XucOWvTMPU&code_challenge_method=S256&state=eZHL55ni-pHkt9fIYllho59-Z5bqB7hYFocPWitvXbM


After authorizing, you'll see a code. Paste it below.

Authorization code: """

MINIMAX_OUTPUT = """Starting Hermes login via MiniMax (global) OAuth...
Portal: https://api.minimax.io

To continue:
  1. Open: https://platform.minimax.io/oauth-authorize?user_code=KAP6-ZBAT&client=OpenClaw
  2. If prompted, enter code: KAP6-ZBAT
Waiting for approval...
"""


def test_extract_oauth_prompt_skips_the_portal_banner() -> None:
    """The `Portal:` host line precedes the real link and must not win."""
    hermes = _import_hermes()

    url, code = hermes.extract_oauth_prompt(NOUS_OUTPUT)

    assert url == (
        'https://portal.nousresearch.com/manage-subscription?user_code=52DK-A59Z'
    )
    assert code == '52DK-A59Z'


def test_extract_oauth_prompt_strips_ansi_and_reads_the_next_line() -> None:
    """OpenAI Codex colourises both values and puts the URL below its label."""
    hermes = _import_hermes()

    url, code = hermes.extract_oauth_prompt(CODEX_OUTPUT)

    # No escape sequence may survive into the QR payload.
    assert url == 'https://auth.openai.com/codex/device'
    # Codex is the case where the code is *not* carried in the URL, so losing
    # it would leave the user unable to finish.
    assert code == 'L0JT-CIPSL'


def test_extract_oauth_prompt_handles_a_query_string_url() -> None:
    """A URL with `&` params survives intact."""
    hermes = _import_hermes()

    url, code = hermes.extract_oauth_prompt(MINIMAX_OUTPUT)

    assert url == (
        'https://platform.minimax.io/oauth-authorize?user_code=KAP6-ZBAT&client=OpenClaw'
    )
    assert code == 'KAP6-ZBAT'


def test_extract_oauth_prompt_returns_none_before_a_url_appears() -> None:
    """Partial output must not yield a half-parsed prompt."""
    hermes = _import_hermes()

    assert hermes.extract_oauth_prompt(
        'Starting Hermes login via Nous Portal...\n',
    ) == (
        None,
        None,
    )


class _FakeStdout:
    """Streams canned lines, then blocks like the real process does."""

    def __init__(self, output: str) -> None:
        self._lines = [f'{line}\n'.encode() for line in output.splitlines()]

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        # The real CLI does not close stdout after printing the block — it sits
        # polling for approval. Sleeping (rather than returning b'') is what
        # makes the grace period meaningful in this test.
        await asyncio.sleep(3600)
        return b''


class _FakeProcess:
    def __init__(self, output: str) -> None:
        self.stdout = _FakeStdout(output)


def _provider(hermes: HermesModule, provider_id: str) -> HermesOAuthProviderProtocol:
    return next(p for p in hermes.HERMES_OAUTH_PROVIDERS if p.id == provider_id)


async def test_read_oauth_prompt_waits_for_a_code_printed_after_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI Codex prints its code several lines below the URL.

    Returning as soon as a URL appears strands the user with a QR and no code
    to type — the other providers hide this by carrying the code in the URL's
    own `user_code` parameter, so both arrive on one line.
    """
    hermes = _import_hermes()
    monkeypatch.setattr(hermes, 'HERMES_OAUTH_CODE_GRACE_SECONDS', 0.5)
    transcript: list[str] = []

    url, code = await hermes._read_oauth_prompt(  # noqa: SLF001
        _FakeProcess(CODEX_OUTPUT),
        _provider(hermes, 'openai-codex'),
        transcript,
    )

    assert url == 'https://auth.openai.com/codex/device'
    assert code == 'L0JT-CIPSL'


async def test_read_oauth_prompt_gives_up_on_a_code_that_never_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A device-code provider that prints no code must not hang the view."""
    hermes = _import_hermes()
    monkeypatch.setattr(hermes, 'HERMES_OAUTH_CODE_GRACE_SECONDS', 0.1)
    transcript: list[str] = []

    url, code = await hermes._read_oauth_prompt(  # noqa: SLF001
        _FakeProcess('Open this: https://example.test/device\n'),
        _provider(hermes, 'openai-codex'),
        transcript,
    )

    assert url == 'https://example.test/device'
    assert code is None


async def test_read_oauth_prompt_returns_at_once_for_the_code_paste_flow() -> None:
    """Anthropic has no device code, so nothing should be waited for."""
    hermes = _import_hermes()
    transcript: list[str] = []

    url, code = await hermes._read_oauth_prompt(  # noqa: SLF001
        _FakeProcess(ANTHROPIC_OUTPUT),
        _provider(hermes, 'anthropic'),
        transcript,
    )

    assert url is not None
    assert url.startswith('https://claude.ai/oauth/authorize')
    assert code is None


def test_oauth_providers_exclude_only_qwen() -> None:
    """Every OAuth provider we can drive is offered.

    `qwen-oauth` is the sole omission: it delegates to a separate `qwen` binary
    that is absent from the image, so it aborts before printing anything a menu
    could use.
    """
    hermes = _import_hermes()

    ids = [provider.id for provider in hermes.HERMES_OAUTH_PROVIDERS]

    assert ids == [
        'nous',
        'openai-codex',
        'xai-oauth',
        'minimax-oauth',
        'anthropic',
    ]
    assert 'qwen-oauth' not in ids


def test_only_anthropic_needs_a_pasted_code() -> None:
    """The code-paste path is opt-in; device-code providers must not take it."""
    hermes = _import_hermes()

    needs_code = {p.id for p in hermes.HERMES_OAUTH_PROVIDERS if p.needs_code}

    assert needs_code == {'anthropic'}


def test_extract_oauth_prompt_ignores_a_pkce_url_without_a_device_code() -> None:
    """Anthropic's URL has no device code, and none may be invented from it.

    Its `client_id`/`state` params carry long hyphenated runs that a device-code
    pattern can match by chance, which would print a meaningless code to the
    user, so the code scan is switched off for this flow.
    """
    hermes = _import_hermes()

    url, code = hermes.extract_oauth_prompt(
        ANTHROPIC_OUTPUT,
        expect_device_code=False,
    )

    assert url is not None
    assert url.startswith('https://claude.ai/oauth/authorize?code=true')
    assert 'code_challenge_method=S256' in url
    assert code is None


def test_hermes_entry_lists_all_secret_keys() -> None:
    """Uninstall clears the API server key, LLM provider and dashboard creds."""
    hermes = _import_hermes()

    assert hermes.ENTRY.secret_keys == (
        hermes.HERMES_API_SERVER_KEY_SECRET,
        *hermes.HERMES_LLM_PROVIDER_SECRET_KEYS,
        *hermes.HERMES_DASHBOARD_AUTH_SECRET_KEYS,
    )
    assert hermes.ENTRY.cleanup is not None


def test_cleanup_hermes_removes_assistant_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cleanup hook deregisters the assistant LLM provider."""
    hermes = _import_hermes()
    fake_store = _FakeStore()
    monkeypatch.setattr(hermes, 'store', fake_store)

    hermes._cleanup_hermes()  # noqa: SLF001

    # Match by class name, not isinstance (see note in the register test).
    remove_actions = cast(
        'list[AssistantRemoveGenericLLMProviderAction]',
        [
            action
            for action in fake_store.dispatched
            if type(action).__name__ == 'AssistantRemoveGenericLLMProviderAction'
        ],
    )
    assert len(remove_actions) == 1
    assert remove_actions[0].provider_id == 'hermes'
