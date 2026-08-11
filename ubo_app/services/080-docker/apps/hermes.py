"""Hermes Agent + Dashboard + WebUI Docker composition."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import secrets as py_secrets
from typing import TYPE_CHECKING, NamedTuple

import aiohttp
import dotenv

from apps._registry import COMPOSITIONS_PATH, ContainerEntry
from ubo_app.constants import CONFIG_PATH
from ubo_app.constants.assistant import (
    ANTHROPIC_API_KEY_SECRET_ID,
    BRAVE_SEARCH_API_KEY_SECRET_ID,
    DEEPSEEK_API_KEY_SECRET_ID,
    ELEVENLABS_API_KEY_SECRET_ID,
    GENERIC_LLM_PROVIDER_API_KEY_SECRET_TEMPLATE,
    GENERIC_LLM_PROVIDER_BASE_URL_SECRET_TEMPLATE,
    GENERIC_LLM_PROVIDER_MODEL_SECRET_TEMPLATE,
    GOOGLE_API_KEY_SECRET_ID,
    GROK_API_KEY_SECRET_ID,
    MISTRAL_API_KEY_SECRET_ID,
    OPENAI_API_KEY_SECRET_ID,
    OPENROUTER_API_KEY_SECRET_ID,
    QWEN_API_KEY_SECRET_ID,
)
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import (
    MenuItemData,
    OpenRenderAction,
    StackPopAction,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
    UpdateRenderPropsAction,
)
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantAddGenericLLMProviderAction,
    AssistantRemoveGenericLLMProviderAction,
)
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

HERMES_COMPOSITION_ID = 'hermes'
# The `hermes` user inside the images. The WebUI container chowns the shared
# state directory to it on start, so anything we create in there has to end up
# owned by it too.
HERMES_CONTAINER_UID = 10000
HERMES_CONTAINER_GID = 10000
# Persistent host directory for all Hermes state, kept outside the composition
# directory so neither `docker compose down -v` nor the composition-directory
# removal on uninstall can destroy it. This decouples config/skills/sessions/
# memories/API keys from the disposable Docker image.
HERMES_DATA_PATH = CONFIG_PATH / 'hermes-data'
HERMES_COMPOSE_URL = (
    'https://raw.githubusercontent.com/nesquena/hermes-webui'
    '/master/docker-compose.three-container.yml'
)
HERMES_GATEWAY_PORT = 8642
HERMES_DASHBOARD_PORT = 9119
HERMES_WEBUI_PORT = 8787
HERMES_API_SERVER_KEY_SECRET = 'hermes_api_server_key'  # noqa: S105

# Dashboard sign-in credentials. Since the June 2026 Hermes hardening the
# dashboard refuses to start on a non-loopback bind unless an auth provider is
# registered, and `--insecure` is a no-op that can no longer bypass the gate.
# The container always binds 0.0.0.0 internally — that is what makes the
# published port reachable at all — so the gate engages regardless of whether
# the *host* side is bound to loopback or to the LAN. Credentials are therefore
# mandatory in both modes, not only when "Expose to LAN" is on.
HERMES_DASHBOARD_USERNAME_SECRET = 'hermes_dashboard_username'  # noqa: S105
HERMES_DASHBOARD_PASSWORD_SECRET = 'hermes_dashboard_password'  # noqa: S105
HERMES_DASHBOARD_SESSION_SECRET = 'hermes_dashboard_session_secret'  # noqa: S105
HERMES_DASHBOARD_AUTH_SECRET_KEYS = (
    HERMES_DASHBOARD_USERNAME_SECRET,
    HERMES_DASHBOARD_PASSWORD_SECRET,
    HERMES_DASHBOARD_SESSION_SECRET,
)
HERMES_DASHBOARD_DEFAULT_USERNAME = 'ubo'


class HermesApiKeyImport(NamedTuple):
    """A ubo-held API key that Hermes can consume under its own env var name."""

    env_var: str
    secret_id: str
    label: str


# ubo secrets that map onto a provider Hermes recognises first-class, keyed by
# the env var name Hermes documents for it. Deliberately not exhaustive over
# ubo's secrets: Cerebras, Venice, Deepgram, AssemblyAI and Rime have no
# documented Hermes env var (Cerebras would need a hand-written custom provider
# entry), and copying a credential into a container that will never read it is
# pure exposure for no capability.
HERMES_API_KEY_IMPORTS = (
    HermesApiKeyImport(
        'OPENROUTER_API_KEY',
        OPENROUTER_API_KEY_SECRET_ID,
        'OpenRouter',
    ),
    HermesApiKeyImport('OPENAI_API_KEY', OPENAI_API_KEY_SECRET_ID, 'OpenAI'),
    HermesApiKeyImport('ANTHROPIC_API_KEY', ANTHROPIC_API_KEY_SECRET_ID, 'Anthropic'),
    HermesApiKeyImport('GEMINI_API_KEY', GOOGLE_API_KEY_SECRET_ID, 'Google Gemini'),
    HermesApiKeyImport('XAI_API_KEY', GROK_API_KEY_SECRET_ID, 'xAI (Grok)'),
    HermesApiKeyImport('MISTRAL_API_KEY', MISTRAL_API_KEY_SECRET_ID, 'Mistral'),
    HermesApiKeyImport('DEEPSEEK_API_KEY', DEEPSEEK_API_KEY_SECRET_ID, 'DeepSeek'),
    HermesApiKeyImport('DASHSCOPE_API_KEY', QWEN_API_KEY_SECRET_ID, 'Qwen'),
    HermesApiKeyImport(
        'BRAVE_SEARCH_API_KEY',
        BRAVE_SEARCH_API_KEY_SECRET_ID,
        'Brave Search',
    ),
    HermesApiKeyImport(
        'ELEVENLABS_API_KEY',
        ELEVENLABS_API_KEY_SECRET_ID,
        'ElevenLabs',
    ),
)

# Auto-registered assistant LLM provider backed by the Hermes gateway's
# OpenAI-compatible API server.
HERMES_LLM_PROVIDER_ID = 'hermes'
HERMES_LLM_PROVIDER_LABEL = 'Hermes'
HERMES_LLM_BASE_URL = f'http://127.0.0.1:{HERMES_GATEWAY_PORT}/v1'
HERMES_LLM_MODEL = 'hermes-agent'
HERMES_LLM_PROVIDER_SECRET_KEYS = (
    GENERIC_LLM_PROVIDER_BASE_URL_SECRET_TEMPLATE.format(
        provider_id=HERMES_LLM_PROVIDER_ID,
    ),
    GENERIC_LLM_PROVIDER_API_KEY_SECRET_TEMPLATE.format(
        provider_id=HERMES_LLM_PROVIDER_ID,
    ),
    GENERIC_LLM_PROVIDER_MODEL_SECRET_TEMPLATE.format(
        provider_id=HERMES_LLM_PROVIDER_ID,
    ),
)


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _patch_compose(content: str) -> str:
    """Patch the upstream compose file for headless Ubo deployment.

    Convert the named ``hermes-home`` volume and the ``/workspace`` bind mount
    into host bind mounts under ``HERMES_DATA_PATH`` (which lives outside the
    composition directory). This decouples all Hermes state — config, skills,
    sessions, memories, API keys — from the Docker image so it survives
    ``docker compose down -v`` and an app delete/reinstall.

    Regexes (not literal strings) are used so the patch keeps working when the
    upstream compose renames the in-container mount targets. The
    ``hermes-agent-src`` volume is left untouched: it is image-derived source
    code, not user data.
    """
    data_path = HERMES_DATA_PATH / 'data'
    workspace_path = HERMES_DATA_PATH / 'workspace'
    # Point every `hermes-home:<target>` mount at the same shared host dir,
    # preserving the container-side path so all three containers keep sharing
    # state (agent/dashboard at /opt/data, webui at /home/hermeswebui/.hermes).
    patched = re.sub(
        r'- hermes-home:(\S+)',
        rf'- {data_path}:\1',
        content,
    )
    # Redirect whatever is bind-mounted at /workspace to our persistent dir,
    # regardless of the upstream source expression (e.g. ~/workspace or
    # ${HERMES_WORKSPACE:-${HOME}/workspace}).
    patched = re.sub(
        r'- \S+:/workspace\b',
        rf'- {workspace_path}:/workspace',
        patched,
    )
    return _inject_api_server_env(patched)


def _inject_api_server_env(content: str) -> str:
    """Ensure the Hermes gateway API server env vars are in compose.

    The vars are injected right after the agent service's ``HERMES_HOME`` env
    line. The first ``HERMES_HOME`` in the file belongs to ``hermes-agent``
    (which runs the gateway); the dashboard's identical line comes later, so a
    single replacement targets the agent only. ``HERMES_HOME`` is matched by
    name — not a fixed value — so this keeps working when upstream changes the
    home path (e.g. ``/opt/data`` → ``/home/hermes/.hermes``).
    """
    required_env_lines = [
        '- API_SERVER_ENABLED=true',
        '- API_SERVER_KEY=${HERMES_API_SERVER_KEY}',
        '- API_SERVER_HOST=0.0.0.0',
        '- GATEWAY_ALLOW_ALL_USERS=true',
    ]
    missing_env_lines = [
        line
        for line in required_env_lines
        if line.split('=', maxsplit=1)[0].strip() not in content
    ]
    if not missing_env_lines:
        return content

    match = re.search(r'^([ \t]*)- HERMES_HOME=.*$', content, flags=re.MULTILINE)
    if match is None:
        logger.warning('Unable to inject Hermes API server env vars')
        return content

    indent = match.group(1)
    needle = match.group(0)
    replacement = '\n'.join(
        [needle, *(f'{indent}{line}' for line in missing_env_lines)],
    )
    return content.replace(needle, replacement, 1)


def _get_or_create_secret(key: str) -> str:
    """Return a persisted random Hermes secret, creating it if needed."""
    value = secrets.read_secret(key)
    if value:
        return value

    value = py_secrets.token_urlsafe(32)
    secrets.write_secret(key=key, value=value)
    return value


def _get_or_create_api_server_key() -> str:
    """Return the persisted Hermes API server key, creating it if needed."""
    return _get_or_create_secret(HERMES_API_SERVER_KEY_SECRET)


# ---------------------------------------------------------------------------
# Dashboard sign-in
# ---------------------------------------------------------------------------


def _has_dashboard_credentials() -> bool:
    """Check whether dashboard sign-in credentials have been collected."""
    return bool(
        secrets.read_secret(HERMES_DASHBOARD_USERNAME_SECRET)
        and secrets.read_secret(HERMES_DASHBOARD_PASSWORD_SECRET),
    )


def _build_dashboard_auth_fields() -> list[InputFieldDescription]:
    """Build the web UI form fields for the dashboard sign-in credentials."""
    return [
        InputFieldDescription(
            name='HERMES_DASHBOARD_USERNAME',
            label='Dashboard username',
            type=InputFieldType.TEXT,
            default_value=HERMES_DASHBOARD_DEFAULT_USERNAME,
            required=True,
        ),
        InputFieldDescription(
            name='HERMES_DASHBOARD_PASSWORD',
            label='Dashboard password',
            type=InputFieldType.PASSWORD,
            description='Used to sign in to the Hermes dashboard.',
            required=True,
        ),
    ]


async def configure_dashboard_auth() -> bool:
    """Prompt for dashboard sign-in credentials and store them as secrets."""
    try:
        _, result = await ubo_input(
            title='Dashboard sign-in',
            prompt='Choose a username and password for the Hermes dashboard.',
            descriptions=[
                WebUIInputDescription(fields=_build_dashboard_auth_fields()),
            ],
        )
    except asyncio.CancelledError:
        return False

    if not result:
        return False

    username = (result.data.get('HERMES_DASHBOARD_USERNAME') or '').strip()
    # The password is stored verbatim — it has to match what the user types
    # into the dashboard's own login form byte for byte.
    password = result.data.get('HERMES_DASHBOARD_PASSWORD') or ''
    if not username or not password:
        logger.warning('Hermes dashboard sign-in submitted incomplete form data')
        return False

    secrets.write_secret(key=HERMES_DASHBOARD_USERNAME_SECRET, value=username)
    secrets.write_secret(key=HERMES_DASHBOARD_PASSWORD_SECRET, value=password)
    return True


# ---------------------------------------------------------------------------
# Optional API key sharing
# ---------------------------------------------------------------------------


def _is_checkbox_on(value: str | None) -> bool:
    """Interpret a CHECKBOX form value. The web UI submits ``on``."""
    return (value or '').strip().lower() in ('on', 'true', '1', 'yes', 'checked')


def _available_api_key_imports() -> list[HermesApiKeyImport]:
    """Return the importable keys the user has actually configured in ubo."""
    return [
        item for item in HERMES_API_KEY_IMPORTS if secrets.read_secret(item.secret_id)
    ]


def _chown_to_container_user(path: Path) -> None:
    """Hand a file we created to the ``hermes`` user inside the containers.

    Best effort: the chown needs privileges we may not hold off-device, and the
    WebUI container chowns this shared directory on start anyway, so failing
    here is recoverable rather than fatal.
    """
    try:
        os.chown(path, HERMES_CONTAINER_UID, HERMES_CONTAINER_GID)
    except OSError:
        logger.warning(
            'Unable to chown Hermes .env to the container user',
            extra={'path': str(path)},
        )


def _write_hermes_dotenv(items: Sequence[HermesApiKeyImport]) -> None:
    """Copy the selected API keys into Hermes' own ``~/.hermes/.env``.

    That file — not ``config.yaml``, and not the composition's Compose ``.env``
    — is where Hermes documents its secrets as living, and it sits in the shared
    state directory so the agent and the WebUI both see it. Keys are set one at
    a time rather than the file being rewritten, so anything Hermes put there
    itself survives. The mode is tightened before the values go in, so the keys
    are never briefly world-readable.
    """
    dotenv_path = HERMES_DATA_PATH / 'data' / '.env'
    dotenv_path.parent.mkdir(exist_ok=True, parents=True)
    dotenv_path.touch(mode=0o600, exist_ok=True)
    dotenv_path.chmod(0o600)
    for item in items:
        value = secrets.read_secret(item.secret_id)
        if value:
            dotenv.set_key(
                dotenv_path=dotenv_path,
                key_to_set=item.env_var,
                value_to_set=value,
            )
    _chown_to_container_user(dotenv_path)


async def configure_api_key_imports() -> None:
    """Offer to share ubo's already-configured API keys with Hermes.

    Entirely optional, and skipped silently when ubo holds none of the keys
    Hermes understands — an empty checklist is worse than no step at all.
    Declining, cancelling or ticking nothing all leave Hermes' ``.env``
    untouched and never block the install.
    """
    available = _available_api_key_imports()
    if not available:
        return

    try:
        _, result = await ubo_input(
            title='Import API keys',
            prompt='Select which of your API keys to share with Hermes.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name=item.env_var,
                            # Masked tail so two keys from the same provider are
                            # tellable apart. `***1234`, parenthesised, is the
                            # shape `apps/_helpers.py` already uses for its
                            # existing-secret picker.
                            label=f'{item.label} '
                            f'({secrets.read_covered_secret(item.secret_id)})',
                            type=InputFieldType.CHECKBOX,
                            description=f'Share as {item.env_var}.',
                            required=False,
                        )
                        for item in available
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return

    if not result:
        return

    selected = [
        item for item in available if _is_checkbox_on(result.data.get(item.env_var))
    ]
    if not selected:
        return

    _write_hermes_dotenv(selected)
    logger.info(
        'Shared API keys with Hermes',
        extra={'variables': [item.env_var for item in selected]},
    )


def _compose_env_item(name: str, value: str) -> str:
    """Render a ``NAME=value`` compose environment entry safely.

    ``$`` is doubled so Compose's variable interpolation leaves a user-chosen
    password alone, and the whole entry is emitted as a double-quoted scalar
    (``json.dumps`` output is valid YAML) so quotes, backslashes, colons and
    ``#`` in the value cannot break the document.
    """
    return json.dumps(f'{name}={value.replace("$", "$$")}')


def _write_dashboard_auth_override(composition_path: Path) -> None:
    """Write the compose override registering the dashboard's auth provider.

    A separate override file is used rather than patching the upstream compose
    so the credentials are rewritten wholesale on every prepare — which is what
    makes "Dashboard Sign-in" take effect on the next start — and never have to
    be located and replaced inside a file we do not own. ``docker compose`` runs
    with the composition directory as its working directory, so it picks
    ``docker-compose.override.yml`` up automatically.
    """
    username = secrets.read_secret(HERMES_DASHBOARD_USERNAME_SECRET)
    password = secrets.read_secret(HERMES_DASHBOARD_PASSWORD_SECRET)
    if not username or not password:
        logger.warning('Skipping Hermes dashboard auth override; no credentials')
        return

    entries = (
        _compose_env_item('HERMES_DASHBOARD_BASIC_AUTH_USERNAME', username),
        _compose_env_item('HERMES_DASHBOARD_BASIC_AUTH_PASSWORD', password),
        # Stable signing key, so sessions survive a container restart.
        _compose_env_item(
            'HERMES_DASHBOARD_BASIC_AUTH_SECRET',
            _get_or_create_secret(HERMES_DASHBOARD_SESSION_SECRET),
        ),
    )
    composition_path.joinpath('docker-compose.override.yml').write_text(
        'services:\n  hermes-dashboard:\n    environment:\n'
        + ''.join(f'      - {entry}\n' for entry in entries),
    )


def _reconfigure_dashboard_auth_action() -> None:
    """Start the dashboard credential re-prompt, returning nothing."""
    create_task(reconfigure_dashboard_auth())


async def reconfigure_dashboard_auth() -> bool:
    """Re-prompt for dashboard credentials and rewrite the compose override."""
    if not await configure_dashboard_auth():
        return False
    _write_dashboard_auth_override(COMPOSITIONS_PATH / HERMES_COMPOSITION_ID)
    return True


# ---------------------------------------------------------------------------
# Provider OAuth sign-in
# ---------------------------------------------------------------------------


class HermesOAuthProvider(NamedTuple):
    """A Hermes provider whose credentials come from an OAuth flow."""

    id: str
    label: str
    icon: str
    # True when the flow ends by reading an authorization code back from stdin
    # rather than polling a device code.
    needs_code: bool = False


# Verified against Hermes v0.20.0 on a device, from the six ids in the CLI's own
# `_OAUTH_CAPABLE_PROVIDERS`. `qwen-oauth` is the one omission: it aborts with
# `Qwen CLI credentials not found` because it delegates to a separate `qwen`
# binary that is not in the image, so there is nothing a menu can drive.
HERMES_OAUTH_PROVIDERS = (
    HermesOAuthProvider('nous', 'Nous Research', '󰧑'),
    HermesOAuthProvider('openai-codex', 'OpenAI Codex', '󰚩'),
    HermesOAuthProvider('xai-oauth', 'xAI Grok', '󰩄'),
    HermesOAuthProvider('minimax-oauth', 'MiniMax', '󰫤'),
    # Anthropic is the odd one out: instead of a device code it redirects to a
    # *hosted* callback (console.anthropic.com), shows the user a code there,
    # and blocks reading that code back from stdin. Since we own the pipe we
    # answer it ourselves — see `needs_code`. Its PKCE verifier lives in the
    # process, so the process must stay alive from URL to code.
    HermesOAuthProvider('anthropic', 'Claude (Anthropic)', '󰛄', needs_code=True),
)

# How long the CLI waits for the user to approve on their phone.
HERMES_OAUTH_TIMEOUT_SECONDS = 300
# How long to keep reading after the URL for a device code printed below it.
HERMES_OAUTH_CODE_GRACE_SECONDS = 5

_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')
_URL_RE = re.compile(r'https?://\S+')
# Device codes render as `52DK-A59Z` (Nous, xAI, MiniMax) or `L0JT-CIPSL`
# (OpenAI Codex).
_DEVICE_CODE_RE = re.compile(r'\b[A-Z0-9]{4}-[A-Z0-9]{4,6}\b')
# Several providers print a `Portal: https://host` banner *before* the link the
# user actually has to open, so the first URL in the stream is the wrong one.
_PORTAL_LINE_RE = re.compile(r'^\s*Portal:', re.IGNORECASE)

_oauth_process: asyncio.subprocess.Process | None = None


def extract_oauth_prompt(
    output: str,
    *,
    expect_device_code: bool = True,
) -> tuple[str | None, str | None]:
    """Pull the verification URL and device code out of Hermes' login output.

    Two traps, both observed on real output: OpenAI Codex wraps the URL and the
    code in ANSI colour sequences (and puts the URL on the line *after* its
    label), and Nous/MiniMax print a `Portal:` host banner ahead of the real
    link. Stripping colour and skipping the banner line handles both without
    tying the parser to any provider's exact wording.

    ``expect_device_code`` is False for the code-paste flow, whose URL carries a
    long PKCE ``state``/``client_id``; scanning that for a device code that does
    not exist risks a chance match on a hyphenated all-caps run.
    """
    plain = _ANSI_ESCAPE_RE.sub('', output)

    url = None
    for line in plain.splitlines():
        if _PORTAL_LINE_RE.match(line):
            continue
        if (match := _URL_RE.search(line)) is not None:
            url = match.group(0).rstrip('.,')
            break

    if not expect_device_code:
        return url, None

    code_match = _DEVICE_CODE_RE.search(plain)
    return url, code_match.group(0) if code_match else None


async def _terminate_oauth_process() -> None:
    """Stop a login already in flight so two flows never race."""
    global _oauth_process
    process, _oauth_process = _oauth_process, None
    if process is None or process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=5)


def _notify_oauth_result(
    provider: HermesOAuthProvider,
    *,
    succeeded: bool,
    transcript: str = '',
) -> None:
    """Report the outcome, carrying the CLI transcript on failure.

    The transcript is what makes an upstream wording change diagnosable rather
    than a silent hang, so it rides along as extra information.
    """
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                title='Hermes',
                content=f'{provider.label} '
                + ('signed in' if succeeded else 'sign-in failed'),
                display_type=NotificationDisplayType.FLASH
                if succeeded
                else NotificationDisplayType.STICKY,
                color='#4CAF50' if succeeded else '#D32F2F',
                icon='󰄬' if succeeded else '󰜺',
                chime=Chime.DONE if succeeded else Chime.FAILURE,
                extra_information=None
                if succeeded or not transcript
                else ReadableInformation(text=transcript),
            ),
        ),
    )


def build_oauth_qr_props(url: str, code: str | None) -> dict[str, str]:
    """Build the ``qr_code`` render props for a login prompt.

    The QR always encodes the bare URL, so a scan works regardless of what is
    written around it. The device code goes in ``caption``, not the label: the
    code is not part of the link and must not be rendered inside one, and on
    its own line it stays readable while typing it in on another device.
    """
    return {
        'value': url,
        'label': url,
        'caption': f'Code: {code}' if code else '',
    }


async def _read_oauth_prompt(
    process: asyncio.subprocess.Process,
    provider: HermesOAuthProvider,
    transcript: list[str],
) -> tuple[str | None, str | None]:
    """Read stdout until both the URL and any device code have appeared.

    Stopping at the URL is not enough. Nous, xAI and MiniMax carry the code in
    the URL's own ``user_code`` parameter, so both land on the same line — but
    OpenAI Codex prints its code several lines *later*, and returning early
    there leaves the user staring at a QR with no code to type. Once the URL is
    in hand we therefore keep reading for a short grace period; the stream is
    unbuffered, so the rest of the block arrives immediately or not at all.
    """
    if process.stdout is None:
        return None, None

    expect_device_code = not provider.needs_code
    loop = asyncio.get_running_loop()
    url = code = None
    deadline: float | None = None
    while True:
        try:
            line = await asyncio.wait_for(
                process.stdout.readline(),
                None if deadline is None else max(deadline - loop.time(), 0),
            )
        except TimeoutError:
            break
        if not line:
            break

        transcript.append(line.decode(errors='replace'))
        url, code = extract_oauth_prompt(
            ''.join(transcript),
            expect_device_code=expect_device_code,
        )
        if url and (code or not expect_device_code):
            break
        if url and deadline is None:
            deadline = loop.time() + HERMES_OAUTH_CODE_GRACE_SECONDS

    return url, code


async def _prompt_for_authorization_code(provider: HermesOAuthProvider) -> str | None:
    """Ask the user for the code the provider showed them after approving."""
    try:
        _, result = await ubo_input(
            title=f'{provider.label} code',
            prompt='Paste the authorization code shown after you approve access.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='code',
                            label='Authorization code',
                            type=InputFieldType.TEXT,
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return None

    if not result:
        return None
    return (result.data.get('code') or '').strip() or None


async def _answer_code_prompt(
    process: asyncio.subprocess.Process,
    provider: HermesOAuthProvider,
) -> bool:
    """Collect the authorization code and hand it to the waiting process."""
    code = await _prompt_for_authorization_code(provider)
    if code is None or process.stdin is None:
        return False
    process.stdin.write(f'{code}\n'.encode())
    await process.stdin.drain()
    process.stdin.close()
    return True


async def _perform_oauth(provider: HermesOAuthProvider) -> None:
    """Run a provider's OAuth login in the container, showing its URL as a QR."""
    global _oauth_process  # noqa: PLW0603
    await _terminate_oauth_process()

    store.dispatch(
        OpenRenderAction(
            kind='status',
            title=f'{provider.label} Sign In',
            props={'text': 'Starting…', 'text_font_size': 16},
        ),
    )

    transcript: list[str] = []
    succeeded = False
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            'docker',
            'compose',
            'exec',
            # No pty: keeps the stream parseable.
            '-T',
            # Hermes block-buffers stdout when it is a pipe rather than a tty,
            # which would withhold the URL until the process exits — long after
            # the login it describes has timed out.
            '-e',
            'PYTHONUNBUFFERED=1',
            'hermes-agent',
            'hermes',
            'auth',
            'add',
            provider.id,
            '--type',
            'oauth',
            '--no-browser',
            '--timeout',
            str(HERMES_OAUTH_TIMEOUT_SECONDS),
            cwd=COMPOSITIONS_PATH / HERMES_COMPOSITION_ID,
            # stdin stays open: the code-paste flow is answered through it.
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        _oauth_process = process
        if process.stdout is None:
            return

        url, code = await _read_oauth_prompt(process, provider, transcript)

        if url is None:
            await process.wait()
            return

        store.dispatch(
            UpdateRenderPropsAction(
                kind='status',
                next_kind='qr_code',
                title=f'{provider.label} Sign In',
                props=build_oauth_qr_props(url, code),
            ),
        )

        if provider.needs_code and not await _answer_code_prompt(process, provider):
            return

        await process.wait()
        succeeded = process.returncode == 0
    except Exception:
        logger.exception('Hermes OAuth login failed', extra={'provider': provider.id})
    finally:
        _oauth_process = None
        # Covers every early return above — a cancelled code prompt, a stream
        # that ended without a URL, an exception — so an abandoned login can
        # never outlive its view.
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
        store.dispatch(StackPopAction())
        _notify_oauth_result(
            provider,
            succeeded=succeeded,
            transcript=''.join(transcript),
        )


def _oauth_action(provider: HermesOAuthProvider) -> Callable[[], None]:
    """Build a menu handler that starts a login and returns nothing.

    Returning ``None`` is load-bearing. ``_handle_execute_menu_action`` pushes
    a menu named after the item's key whenever a handler returns a non-``None``
    result, which is how items that navigate are distinguished from items that
    just act. Handing back the ``Task`` from ``create_task`` therefore stacked
    an empty "Openai Codex" page under the sign-in view, and popping the view
    on success landed the user on that instead of back at the provider list.
    """

    def start() -> None:
        create_task(_perform_oauth(provider))

    return start


def _add_oauth_menu(
    menu_id: str,
    items: list[MenuItemData],
    action_ids: dict[str, list[str]],
) -> None:
    """Add the OAuth submenu and populate it with the supported providers.

    Mirrors the Ports submenu in ``menus.py``: a nav item pushes ``menu_key``,
    and the menu it lands on is filled by a dynamic-menu dispatch. Every action
    id is appended to ``action_ids`` so the menu builder unregisters it before
    the next render.
    """
    nav_id = 'docker:hermes:oauth'
    action_ids[menu_id].append(nav_id)
    register_action(
        nav_id,
        lambda: store.dispatch(StackPushMenuAction(menu_key='oauth')),
    )
    items.append(
        MenuItemData(key='oauth', label='OAuth', icon='󰌆', action_id=nav_id),
    )

    oauth_items: list[MenuItemData] = []
    for provider in HERMES_OAUTH_PROVIDERS:
        provider_action_id = f'docker:hermes:oauth:{provider.id}'
        action_ids[menu_id].append(provider_action_id)
        register_action(provider_action_id, _oauth_action(provider))
        oauth_items.append(
            MenuItemData(
                key=provider.id,
                label=provider.label,
                icon=provider.icon,
                action_id=provider_action_id,
            ),
        )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=f'docker:image:{HERMES_COMPOSITION_ID}:oauth',
            title='OAuth',
            items=tuple(oauth_items),
            placeholder='No providers',
        ),
    )


def _menu_actions(
    menu_id: str,
    items: list[MenuItemData],
    action_ids: dict[str, list[str]],
) -> None:
    """Add the Hermes-specific items to the app menu."""
    action_id = 'docker:hermes:dashboard-auth'
    action_ids[menu_id].append(action_id)
    # Returns None deliberately — see `_oauth_action`; handing back a Task
    # would stack an empty "Dashboard Auth" page over the menu.
    register_action(action_id, _reconfigure_dashboard_auth_action)
    items.append(
        MenuItemData(
            key='dashboard-auth',
            label='Dashboard Sign-in',
            icon='󰌾',
            action_id=action_id,
        ),
    )
    _add_oauth_menu(menu_id, items, action_ids)


def _write_hermes_env(composition_path: Path) -> None:
    """Write compose env for Hermes.

    UID/GID are set to the hermes user inside the image so the WebUI container
    chowns the shared hermes-home volume to the correct user. Setting UID=0
    would cause the WebUI to chown everything to root, making the volume
    inaccessible to the hermes-agent (which runs as that user).
    """
    api_server_key = _get_or_create_api_server_key()
    composition_path.joinpath('.env').write_text(
        f'UID={HERMES_CONTAINER_UID}\n'
        f'GID={HERMES_CONTAINER_GID}\n'
        f'HERMES_UID={HERMES_CONTAINER_UID}\n'
        f'HERMES_GID={HERMES_CONTAINER_GID}\n'
        'API_SERVER_ENABLED=true\n'
        f'HERMES_API_SERVER_KEY={api_server_key}\n',
    )


def _register_assistant_provider(api_server_key: str) -> None:
    """Register the Hermes gateway as a named generic LLM provider.

    Writes the per-provider credentials and upserts the provider entry so it
    shows up under Assistant → Language Model without any manual setup. It
    is *not* auto-selected — the user picks it like any other provider.
    """
    base_url_key, api_key_key, model_key = HERMES_LLM_PROVIDER_SECRET_KEYS
    secrets.write_secret(key=base_url_key, value=HERMES_LLM_BASE_URL)
    secrets.write_secret(key=api_key_key, value=api_server_key)
    secrets.write_secret(key=model_key, value=HERMES_LLM_MODEL)
    store.dispatch(
        AssistantAddGenericLLMProviderAction(
            provider_id=HERMES_LLM_PROVIDER_ID,
            label=HERMES_LLM_PROVIDER_LABEL,
        ),
    )


def _cleanup_hermes() -> None:
    """Deregister the Hermes assistant LLM provider on uninstall.

    The provider's secrets are cleared by the assistant service's
    removed-event handler (and ``ENTRY.secret_keys`` as a fallback when the
    assistant service isn't loaded).
    """
    store.dispatch(
        AssistantRemoveGenericLLMProviderAction(
            provider_id=HERMES_LLM_PROVIDER_ID,
        ),
    )


# ---------------------------------------------------------------------------
# Prepare / reconfigure
# ---------------------------------------------------------------------------


def _is_hermes_configured() -> bool:
    composition_path = COMPOSITIONS_PATH / HERMES_COMPOSITION_ID
    return (composition_path / 'docker-compose.yml').exists() and (
        composition_path / '.env'
    ).exists()


async def prepare_hermes() -> bool:
    """Prepare Hermes Agent + Dashboard + WebUI for Docker Composition."""
    try:
        composition_path = COMPOSITIONS_PATH / HERMES_COMPOSITION_ID
        logger.info(
            'Preparing Hermes composition',
            extra={'composition_path': str(composition_path)},
        )

        # Collected up front, before any files are written, so cancelling the
        # form leaves nothing behind. `prepare` runs before every `up`, so this
        # only prompts on the first install (or after the secrets are cleared).
        if not _has_dashboard_credentials():
            if not await configure_dashboard_auth():
                logger.warning('Hermes dashboard sign-in was not configured')
                return False
            # Optional second step of the same first-run setup; never fatal.
            await configure_api_key_imports()

        composition_path.mkdir(exist_ok=True, parents=True)
        # Persistent, image-independent state dirs (idempotent — never clobbers
        # data preserved across a delete/reinstall).
        (HERMES_DATA_PATH / 'data').mkdir(exist_ok=True, parents=True)
        (HERMES_DATA_PATH / 'workspace').mkdir(exist_ok=True, parents=True)

        compose_path = composition_path / 'docker-compose.yml'
        if compose_path.exists():
            compose_content = compose_path.read_text()
        else:
            async with (
                aiohttp.ClientSession() as session,
                session.get(HERMES_COMPOSE_URL) as response,
            ):
                response.raise_for_status()
                compose_content = await response.text()

        compose_content = _patch_compose(compose_content)
        compose_path.write_text(compose_content)

        _write_hermes_env(composition_path)
        _write_dashboard_auth_override(composition_path)

        _register_assistant_provider(_get_or_create_api_server_key())

        metadata = {
            'label': 'Hermes Agent',
            'icon': '󱚣',
            'instructions': (
                'Hermes Agent is installed and running!\n\n'
                f'Gateway: http://{{{{hostname}}}}:{HERMES_GATEWAY_PORT}\n'
                f'Dashboard: http://{{{{hostname}}}}:{HERMES_DASHBOARD_PORT}\n'
                f'WebUI: http://{{{{hostname}}}}:{HERMES_WEBUI_PORT}\n\n'
                'Use the WebUI to chat with Hermes, and use the dashboard to '
                'monitor agent activity, sessions, and resource usage.\n\n'
                'The dashboard asks for the username and password you entered '
                'during setup. Change them with "Dashboard Sign-in" in the '
                'Hermes menu.\n\n'
                'For security these ports are reachable from this device only '
                '(loopback) by default. To open them to your local network, use '
                '"Expose to LAN" in the Hermes menu.'
            ),
            'compose_id': HERMES_COMPOSITION_ID,
        }
        (composition_path / 'metadata.json').write_text(json.dumps(metadata))

    except Exception:
        logger.exception('Failed to prepare Hermes')
        return False
    else:
        return True


ENTRY = ContainerEntry(
    id=HERMES_COMPOSITION_ID,
    label='Hermes Agent',
    icon='󱚣',
    path='nesquena/hermes-webui:latest',
    registry='ghcr.io',
    prepare=prepare_hermes,
    cleanup=_cleanup_hermes,
    is_composition=True,
    category='AI Agents',
    # The dashboard (9119) is gated behind its own basic-auth sign-in, but the
    # gateway (8642) and WebUI (8787) still have none; default to loopback.
    supports_lan_toggle=True,
    secret_keys=(
        HERMES_API_SERVER_KEY_SECRET,
        *HERMES_LLM_PROVIDER_SECRET_KEYS,
        *HERMES_DASHBOARD_AUTH_SECRET_KEYS,
    ),
    menu_actions=_menu_actions,
    ports={
        f'{HERMES_GATEWAY_PORT}/tcp': HERMES_GATEWAY_PORT,
        f'{HERMES_DASHBOARD_PORT}/tcp': HERMES_DASHBOARD_PORT,
        f'{HERMES_WEBUI_PORT}/tcp': HERMES_WEBUI_PORT,
    },
)
