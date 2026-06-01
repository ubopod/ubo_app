"""Implement `init_service` for assistant service."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
    from ubo_app.store.services.localization import LanguageCode

from engines_registry import (
    IMAGE_GENERATOR_ENGINES,
    LLM_ENGINES,
    STT_ENGINES,
    TTS_ENGINES,
)
from redux import AutorunOptions

from ubo_app.colors import DANGER_COLOR, INFO_COLOR, WARNING_COLOR
from ubo_app.constants import SECRETS_PATH
from ubo_app.constants.assistant import (
    ANTHROPIC_API_KEY_SECRET_ID,
    ASSEMBLYAI_API_KEY_SECRET_ID,
    CEREBRAS_API_KEY_SECRET_ID,
    DEEPGRAM_API_KEY_SECRET_ID,
    DEEPSEEK_API_KEY_SECRET_ID,
    DEFAULT_LLM_OLLAMA_MODEL,
    ELEVENLABS_API_KEY_SECRET_ID,
    ELEVENLABS_VOICE_ID,
    GENERIC_LLM_API_KEY_SECRET_ID,
    GENERIC_LLM_BASE_URL_SECRET_ID,
    GENERIC_LLM_MODEL_SECRET_ID,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
    GROK_API_KEY_SECRET_ID,
    MISTRAL_API_KEY_SECRET_ID,
    OLLAMA_RAM_LIMIT_NOTIFICATION_ID,
    OPENAI_API_KEY_SECRET_ID,
    OPENROUTER_API_KEY_SECRET_ID,
    QWEN_API_KEY_SECRET_ID,
    RIME_API_KEY_SECRET_ID,
    VENICE_API_KEY_SECRET_ID,
)
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.engines.kokoro import KokoroEngine
from ubo_app.engines.kokoro_catalog import (
    DEFAULT_KOKORO_VOICE_ID,
    KOKORO_LANGUAGES,
)
from ubo_app.engines.kokoro_catalog import language_for as kokoro_language_for
from ubo_app.engines.kokoro_catalog import (
    visible_languages as kokoro_visible_languages,
)
from ubo_app.engines.kokoro_catalog import voice_for as kokoro_voice_for
from ubo_app.engines.kokoro_catalog import voice_label as kokoro_voice_label
from ubo_app.engines.ollama import OllamaEngine
from ubo_app.engines.ollama_catalog import (
    OLLAMA_CATALOG,
    fits_in_ram,
    format_size,
    normalize_model_tag,
    required_ram_bytes,
)
from ubo_app.engines.piper import PiperEngine
from ubo_app.engines.piper_catalog import (
    DEFAULT_PIPER_VOICE_ID,
    PIPER_LANGUAGES,
    language_for,
    visible_languages,
    voice_for,
    voice_label,
)
from ubo_app.engines.vosk import VoskEngine
from ubo_app.engines.vosk_catalog import (
    DEFAULT_VOSK_MODEL_ID,
    VOSK_LANGUAGES,
)
from ubo_app.engines.vosk_catalog import language_for as vosk_language_for
from ubo_app.engines.vosk_catalog import model_for as vosk_model_for
from ubo_app.engines.vosk_catalog import model_label as vosk_model_label
from ubo_app.engines.vosk_catalog import visible_languages as vosk_visible_languages
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuGoBackAction,
    MenuItemData,
    OpenRenderAction,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
    StackPushPromptAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import register_menu_content_dependency
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    DEFAULT_MODELS,
    AssistanceAudioFrame,
    AssistanceImageFrame,
    AssistantAddMcpServerEvent,
    AssistantDeleteMcpServerEvent,
    AssistantDownloadKokoroAction,
    AssistantDownloadKokoroEvent,
    AssistantDownloadOllamaModelAction,
    AssistantDownloadOllamaModelEvent,
    AssistantDownloadPiperVoiceAction,
    AssistantDownloadPiperVoiceEvent,
    AssistantDownloadVoskModelAction,
    AssistantDownloadVoskModelEvent,
    AssistantHandleReportEvent,
    AssistantImageGeneratorName,
    AssistantLLMName,
    AssistantSetMcpServersAction,
    AssistantSetOllamaThinkingAction,
    AssistantSetSelectedImageGeneratorAction,
    AssistantSetSelectedKokoroVoiceAction,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
    AssistantSetSelectedPiperVoiceAction,
    AssistantSetSelectedSTTAction,
    AssistantSetSelectedTTSAction,
    AssistantSetSelectedVoskModelAction,
    AssistantSTTName,
    AssistantSyncMcpServersAction,
    AssistantSyncMcpServersEvent,
    AssistantToggleMcpServerEvent,
    AssistantTTSName,
    AssistantUpdateProvidersAction,
    McpServerMetadata,
    McpServerType,
)
from ubo_app.store.services.audio import AudioPlayAudioSequenceAction
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    ItemParameters,
    build_selection_menu,
)
from ubo_app.utils.persistent_store import register_persistent_store


def _get_selected_item_parameters(*, is_offline: bool) -> ItemParameters:
    return {
        **SELECTED_ITEM_PARAMETERS,
        'background_color': INFO_COLOR if is_offline else WARNING_COLOR,
        'color': '#ffffff',
    }


def _get_unselected_item_parameters(*, is_offline: bool) -> ItemParameters:
    return {
        **UNSELECTED_ITEM_PARAMETERS,
        'background_color': '#000000',
        'color': INFO_COLOR if is_offline else WARNING_COLOR,
    }


def _get_setup_item_parameters(*, is_offline: bool | None = None) -> ItemParameters:
    parameters: ItemParameters = {
        'color': '#ffffff',
        'icon': '󰄬',
    }
    if is_offline is not None:
        parameters['background_color'] = INFO_COLOR if is_offline else WARNING_COLOR
    return parameters


def _get_not_setup_item_parameters(*, is_offline: bool | None = None) -> ItemParameters:
    parameters: ItemParameters = {
        'background_color': '#000000',
        'icon': '',
    }
    if is_offline is not None:
        parameters['color'] = INFO_COLOR if is_offline else WARNING_COLOR
    return parameters


def secrets_modification_time() -> float:
    """Return the modification time of the secrets file."""
    return SECRETS_PATH.stat().st_mtime if SECRETS_PATH.exists() else 0


def _total_ram_bytes() -> int:
    """Return total device RAM in bytes; ``0`` if it can't be determined."""
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:
        logger.exception('Failed to read total RAM via psutil')
        return 0


def _format_ram_gb(bytes_: int) -> str:
    """Render a byte count as a short GB label."""
    return f'{bytes_ / (1024**3):.1f} GB'


def input_mcp_server() -> None:
    """Input MCP server configuration via WebUI."""

    async def act() -> None:
        import asyncio
        import contextlib

        from mcp_servers import save_mcp_server, validate_sse_url, validate_stdio_config

        from ubo_app.store.services.assistant import (
            AssistantAddMcpServerAction,
            SseMcpConfig,
            StdioMcpConfig,
        )

        with contextlib.suppress(asyncio.CancelledError):
            _, result = await ubo_input(
                prompt='Add MCP Server',
                descriptions=[
                    WebUIInputDescription(
                        fields=[
                            InputFieldDescription(
                                name='name',
                                label='Server Name',
                                type=InputFieldType.TEXT,
                                description='Friendly name for this MCP server',
                                required=True,
                            ),
                            InputFieldDescription(
                                name='type',
                                label='Server Type',
                                type=InputFieldType.SELECT,
                                description='Type of MCP server',
                                options=['stdio', 'sse'],
                                required=True,
                            ),
                            InputFieldDescription(
                                name='config',
                                label='Configuration',
                                type=InputFieldType.LONG,
                                description='For stdio: paste full JSON with '
                                'mcpServers. For sse: paste URL',
                                required=True,
                            ),
                        ],
                    ),
                ],
            )

            if not result or not result.data:
                return

            name = result.data.get('name', '').strip()
            server_type_str = result.data.get('type', '').strip()
            config_str = result.data.get('config', '').strip()

            if not name or not server_type_str or not config_str:
                return

            server_type = McpServerType(server_type_str)

            # Validate and create typed configuration
            if server_type == McpServerType.STDIO:
                is_valid, error_msg, parsed_config = validate_stdio_config(config_str)
                if not is_valid or not parsed_config:
                    logger.error(
                        'Invalid stdio configuration',
                        extra={'error': error_msg},
                    )
                    return
                # Extract server config and create typed object
                mcp_servers_dict = parsed_config.get('mcpServers', {})
                server_config = next(iter(mcp_servers_dict.values()))
                typed_config: StdioMcpConfig | SseMcpConfig = StdioMcpConfig(
                    command=server_config['command'],
                    args=server_config.get('args', []),
                    env=server_config.get('env', {}),
                )
            else:  # SSE
                is_valid, error_msg = validate_sse_url(config_str)
                if not is_valid:
                    logger.error('Invalid SSE URL', extra={'error': error_msg})
                    return
                typed_config = SseMcpConfig(url=config_str)

            # Save to filesystem
            server_id = save_mcp_server(name, server_type, typed_config)

            # Dispatch action to update state
            store.dispatch(
                AssistantAddMcpServerAction(
                    name=name,
                    type=server_type,
                    config=typed_config,
                ),
            )

            logger.info(
                'MCP server added',
                extra={'server_id': server_id, 'server_name': name},
            )

    create_task(act())


def _communicate(event: AssistantHandleReportEvent) -> None:
    """Communicate the assistance."""
    match event.data:
        case AssistanceAudioFrame(audio=sample, index=index, id=id):
            if sample:
                store.dispatch(
                    AudioPlayAudioSequenceAction(
                        sample=sample,
                        id=f'assistant:{event.source_id}:{id}',
                        index=index,
                    ),
                )

        case AssistanceImageFrame() as image:
            store.dispatch(
                OpenRenderAction(
                    kind='image_viewer',
                    props={
                        'image': image.image,
                        'width': image.width,
                        'height': image.height,
                    },
                ),
            )


def _register_persistent_stores() -> None:
    """Register all persistent stores for assistant service."""
    register_persistent_store(
        'assistant:selected_stt',
        lambda state: state.assistant.selected_stt,
    )
    register_persistent_store(
        'assistant:selected_llm',
        lambda state: state.assistant.selected_llm,
    )
    register_persistent_store(
        'assistant:selected_tts',
        lambda state: state.assistant.selected_tts,
    )
    register_persistent_store(
        'assistant:selected_image_generator',
        lambda state: state.assistant.selected_image_generator,
    )
    register_persistent_store(
        'assistant:selected_llm_model',
        lambda state: json.dumps(state.assistant.selected_models),
    )
    register_persistent_store(
        'assistant:ollama_thinking_enabled',
        lambda state: json.dumps(state.assistant.ollama_thinking_enabled),
    )
    register_persistent_store(
        'assistant:enabled_mcp_servers',
        lambda state: json.dumps(list(state.assistant.enabled_mcp_servers)),
    )
    register_persistent_store(
        'assistant:selected_piper_voice',
        lambda state: state.assistant.selected_piper_voice,
    )
    register_persistent_store(
        'assistant:selected_kokoro_voice',
        lambda state: state.assistant.selected_kokoro_voice,
    )


def _setup_autorun_and_handlers() -> tuple:  # noqa: C901, PLR0915
    """Set up all autorun functions and MCP event handlers.

    Returns:
        Tuple of (providers, stt_providers, llm_providers, tts_providers,
                  image_generator_providers, mcp_servers_menu,
                  handle_add_mcp_server, handle_delete_mcp_server)

    """
    _provider_action_ids: list[str] = []
    _stt_action_ids: list[str] = []
    _llm_action_ids: list[str] = []
    _llm_model_select_action_ids: list[str] = []
    _provider_detail_action_ids: list[str] = []
    _tts_action_ids: list[str] = []
    _img_gen_action_ids: list[str] = []
    _mcp_action_ids: list[str] = []
    _mcp_server_unsubscribers: dict[str, Callable] = {}

    # Generic "cancel/dismiss prompt" — dispatched by the Cancel button in
    # the delete-credentials confirmation prompt. Registered once for the
    # service lifetime.
    register_action(
        'assistant:provider-detail:cancel',
        lambda: store.dispatch(MenuGoBackAction()),
        allow_reregister=True,
    )

    # Secrets file monitor - tracks API key changes.
    #
    # Memoisation MUST stay on: the selector returns the secrets-file mtime,
    # which only changes when the file is actually written via
    # ``secrets.write_secret`` / ``clear_secret``. With memoisation off the
    # autorun would re-run on every store dispatch, re-reading the secrets
    # file 17 times per dispatch — and because the returned dict is a fresh
    # object each time, every downstream autorun that includes
    # ``secrets_monitor.value`` in its selector tuple (llm_providers /
    # provider_details / tts_providers / ...) would re-fire too, each calling
    # ``is_setup`` on every engine which opens the secrets file again. That
    # cascade is enough to exhaust the process FD limit on macOS.
    @store.autorun(
        lambda _: secrets_modification_time(),
    )
    def secrets_monitor(_: float) -> dict[str, str | None]:
        """Monitor secrets file changes and return current API keys."""
        return {
            'openai': secrets.read_secret(OPENAI_API_KEY_SECRET_ID),
            'google_cloud': secrets.read_secret(
                GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
            ),
            'grok': secrets.read_secret(GROK_API_KEY_SECRET_ID),
            'elevenlabs_key': secrets.read_secret(ELEVENLABS_API_KEY_SECRET_ID),
            'elevenlabs_voice': secrets.read_secret(ELEVENLABS_VOICE_ID),
            'cerebras': secrets.read_secret(CEREBRAS_API_KEY_SECRET_ID),
            'anthropic': secrets.read_secret(ANTHROPIC_API_KEY_SECRET_ID),
            'qwen': secrets.read_secret(QWEN_API_KEY_SECRET_ID),
            'deepseek': secrets.read_secret(DEEPSEEK_API_KEY_SECRET_ID),
            'openrouter': secrets.read_secret(OPENROUTER_API_KEY_SECRET_ID),
            'mistral': secrets.read_secret(MISTRAL_API_KEY_SECRET_ID),
            'venice': secrets.read_secret(VENICE_API_KEY_SECRET_ID),
            'generic_llm_base_url': secrets.read_secret(
                GENERIC_LLM_BASE_URL_SECRET_ID,
            ),
            'generic_llm_api_key': secrets.read_secret(GENERIC_LLM_API_KEY_SECRET_ID),
            'generic_llm_model': secrets.read_secret(GENERIC_LLM_MODEL_SECRET_ID),
            'deepgram': secrets.read_secret(DEEPGRAM_API_KEY_SECRET_ID),
            'assemblyai': secrets.read_secret(ASSEMBLYAI_API_KEY_SECRET_ID),
            'rime': secrets.read_secret(RIME_API_KEY_SECRET_ID),
        }

    def _deduped_providers() -> list[AIProviderMixin]:
        """Return all engines deduplicated by class, sorted for display."""
        return sorted(
            {
                type(engine): engine
                for engine in {
                    *STT_ENGINES.values(),
                    *LLM_ENGINES.values(),
                    *TTS_ENGINES.values(),
                    *IMAGE_GENERATOR_ENGINES.values(),
                }
                if engine is not None
            }.values(),
            key=lambda p: (
                isinstance(p, RemoteMixin),
                p.label.lower(),
            ),
        )

    def _llm_name_for(provider: NeedsSetupMixin) -> AssistantLLMName | None:
        return next(
            (name for name, eng in LLM_ENGINES.items() if eng is provider),
            None,
        )

    def _has_model_picker(provider: NeedsSetupMixin) -> bool:
        return _llm_name_for(provider) is not None and bool(
            getattr(provider, 'CURATED_MODELS', ()),
        )

    @store.autorun(
        lambda state: (
            secrets_monitor.value,
            state.assistant.provider_setup_status,
        ),
    )
    def providers(_: tuple[dict[str, str | None], dict[str, bool]]) -> None:
        """Update dynamic menu for provider management."""
        for action_id in _provider_action_ids:
            unregister_action(action_id)
        _provider_action_ids.clear()

        items: list[MenuItemData] = []
        for provider in _deduped_providers():
            if isinstance(
                provider,
                (OllamaEngine, PiperEngine, KokoroEngine, VoskEngine),
            ):
                # Ollama, Piper, Kokoro, and Vosk share the pattern: the
                # catalog picker is both the setup path *and* the
                # day-to-day picker, so we always offer the drill-in
                # regardless of whether the current selection has been
                # downloaded yet.
                action_id = f'assistant:open-provider:{provider.name}'
                _provider_action_ids.append(action_id)
                register_action(
                    action_id,
                    lambda p=provider: store.dispatch(
                        StackPushMenuAction(menu_key=f'provider:{p.name}'),
                    ),
                    allow_reregister=True,
                )
                params = (
                    _get_setup_item_parameters()
                    if provider.is_setup
                    else _get_not_setup_item_parameters()
                )
                items.append(
                    MenuItemData(
                        key=provider.name,
                        label=provider.label,
                        icon=params.get('icon', ''),
                        color=params.get('color', '#ffffff'),
                        background_color=params.get('background_color'),
                        action_id=action_id,
                    ),
                )
                continue
            if isinstance(provider, NeedsSetupMixin):
                action_id: str | None
                if provider.is_setup:
                    params = _get_setup_item_parameters()
                    # Only drill into a detail menu when there is something to
                    # manage — credentials in the secrets file (source of
                    # truth) and/or a curated model picker. Local engines
                    # without either (e.g. Piper, Vosk) get a status-only
                    # row.
                    if (
                        provider.has_stored_credentials()
                        or _has_model_picker(provider)
                    ):
                        action_id = f'assistant:open-provider:{provider.name}'
                        _provider_action_ids.append(action_id)
                        register_action(
                            action_id,
                            lambda p=provider: store.dispatch(
                                StackPushMenuAction(menu_key=f'provider:{p.name}'),
                            ),
                            allow_reregister=True,
                        )
                    else:
                        action_id = None
                else:
                    # Not configured — tap to launch setup flow
                    action_id = f'assistant:setup-provider:{provider.name}'
                    _provider_action_ids.append(action_id)
                    register_action(
                        action_id,
                        provider.setup,
                        allow_reregister=True,
                    )
                    params = _get_not_setup_item_parameters()
                items.append(
                    MenuItemData(
                        key=provider.name,
                        label=provider.label,
                        icon=params.get('icon', ''),
                        color=params.get('color', '#ffffff'),
                        background_color=params.get('background_color'),
                        action_id=action_id,
                    ),
                )
            else:
                items.append(
                    MenuItemData(
                        key=provider.name,
                        label=provider.label,
                        icon='󰱒',
                    ),
                )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:providers',
                title='Manage Providers',
                heading='Setup providers to be used by different assistant features',
                sub_heading='',
                items=tuple(items),
            ),
        )

    @store.autorun(
        lambda state: (
            state.assistant.provider_setup_status,
            state.assistant.selected_models,
            secrets_monitor.value,
            state.assistant.ollama_model_capabilities,
            state.assistant.ollama_thinking_enabled,
            state.assistant.selected_piper_voice,
            state.assistant.selected_kokoro_voice,
            state.assistant.selected_vosk_model,
        ),
    )
    def provider_details(  # noqa: C901, PLR0915
        data: tuple[
            dict[str, bool],
            dict[AssistantLLMName, str],
            dict[str, str | None],
            dict[str, tuple[str, ...]],
            dict[str, bool],
            str,
            str,
            str,
        ],
    ) -> None:
        """Build per-provider detail menus reachable from Manage Providers."""
        selected_models = data[1]
        ollama_caps = data[3]
        ollama_thinking = data[4]
        selected_piper_voice = data[5] or DEFAULT_PIPER_VOICE_ID
        selected_kokoro_voice = data[6] or DEFAULT_KOKORO_VOICE_ID
        selected_vosk_model = data[7] or DEFAULT_VOSK_MODEL_ID

        for action_id in _provider_detail_action_ids:
            unregister_action(action_id)
        _provider_detail_action_ids.clear()

        for provider in _deduped_providers():
            if not isinstance(provider, NeedsSetupMixin):
                continue
            if not provider.is_setup and not isinstance(
                provider,
                (OllamaEngine, PiperEngine, KokoroEngine, VoskEngine),
            ):
                continue

            items: list[MenuItemData] = []

            # Ollama (local) gets a categorised picker rather than the generic
            # flat CURATED_MODELS list, plus an optional thinking toggle when
            # the selected model advertises that capability via `show()`.
            if isinstance(provider, OllamaEngine):
                current_model = selected_models.get(
                    AssistantLLMName.OLLAMA,
                    DEFAULT_LLM_OLLAMA_MODEL,
                )
                categories_action = (
                    'assistant:provider-detail:ollama-categories'
                )
                _provider_detail_action_ids.append(categories_action)
                register_action(
                    categories_action,
                    lambda: store.dispatch(
                        StackPushMenuAction(
                            menu_key='ollama:categories',
                        ),
                    ),
                    allow_reregister=True,
                )
                items.append(
                    MenuItemData(
                        key='select-model',
                        label=f'Model: {current_model}',
                        icon='󰧑',
                        action_id=categories_action,
                    ),
                )

                caps = ollama_caps.get(current_model, ())
                if 'thinking' in caps:
                    enabled = ollama_thinking.get(current_model, False)
                    toggle_action = (
                        'assistant:provider-detail:ollama-toggle-thinking'
                    )
                    _provider_detail_action_ids.append(toggle_action)
                    register_action(
                        toggle_action,
                        lambda m=current_model, e=enabled: store.dispatch(
                            AssistantSetOllamaThinkingAction(
                                model=m,
                                enabled=not e,
                            ),
                        ),
                        allow_reregister=True,
                    )
                    items.append(
                        MenuItemData(
                            key='ollama-thinking',
                            label=f'Thinking: {"On" if enabled else "Off"}',
                            icon='󰈸',
                            action_id=toggle_action,
                        ),
                    )

                store.dispatch(
                    UpdateDynamicMenuAction(
                        menu_id=f'assistant:provider:{provider.name}',
                        title=provider.label,
                        heading=provider.label,
                        sub_heading='Manage this provider',
                        items=tuple(items),
                    ),
                )
                continue

            # Piper exposes a Language → Voice drill-down driven by the
            # curated catalog. Always rendered, even before any voice is
            # downloaded, so the user can pick a voice that triggers its
            # first download.
            if isinstance(provider, PiperEngine):
                current_voice = voice_for(selected_piper_voice)
                current_label = (
                    voice_label(current_voice)
                    if current_voice is not None
                    else selected_piper_voice
                )
                voice_action = 'assistant:provider-detail:piper-languages'
                _provider_detail_action_ids.append(voice_action)
                register_action(
                    voice_action,
                    lambda: store.dispatch(
                        StackPushMenuAction(menu_key='piper:languages'),
                    ),
                    allow_reregister=True,
                )
                items.append(
                    MenuItemData(
                        key='select-voice',
                        label=f'Voice: {current_label}',
                        icon='󰔊',
                        action_id=voice_action,
                    ),
                )
                store.dispatch(
                    UpdateDynamicMenuAction(
                        menu_id=f'assistant:provider:{provider.name}',
                        title=provider.label,
                        heading=provider.label,
                        sub_heading='Manage this provider',
                        items=tuple(items),
                    ),
                )
                continue

            # Kokoro mirrors the Piper drill-down. Different from Piper,
            # the bundle download is one-shot for all voices, so once
            # ``is_setup`` is True every voice in the catalog switches
            # instantly without any further file work.
            if isinstance(provider, KokoroEngine):
                current_voice_k = kokoro_voice_for(selected_kokoro_voice)
                current_label_k = (
                    kokoro_voice_label(current_voice_k)
                    if current_voice_k is not None
                    else selected_kokoro_voice
                )
                kokoro_voice_action = 'assistant:provider-detail:kokoro-languages'
                _provider_detail_action_ids.append(kokoro_voice_action)
                register_action(
                    kokoro_voice_action,
                    lambda: store.dispatch(
                        StackPushMenuAction(menu_key='kokoro:languages'),
                    ),
                    allow_reregister=True,
                )
                items.append(
                    MenuItemData(
                        key='select-voice',
                        label=f'Voice: {current_label_k}',
                        icon='󰔊',
                        action_id=kokoro_voice_action,
                    ),
                )
                store.dispatch(
                    UpdateDynamicMenuAction(
                        menu_id=f'assistant:provider:{provider.name}',
                        title=provider.label,
                        heading=provider.label,
                        sub_heading='Manage this provider',
                        items=tuple(items),
                    ),
                )
                continue

            # Vosk exposes a Language → Model drill-down driven by the
            # curated catalog. Always rendered, even before any model is
            # downloaded, so the user can pick a model that triggers its
            # first download.
            if isinstance(provider, VoskEngine):
                current_model_entry = vosk_model_for(selected_vosk_model)
                current_label = (
                    vosk_model_label(current_model_entry)
                    if current_model_entry is not None
                    else selected_vosk_model
                )
                model_action = 'assistant:provider-detail:vosk-languages'
                _provider_detail_action_ids.append(model_action)
                register_action(
                    model_action,
                    lambda: store.dispatch(
                        StackPushMenuAction(menu_key='vosk:languages'),
                    ),
                    allow_reregister=True,
                )
                items.append(
                    MenuItemData(
                        key='select-model',
                        label=f'Model: {current_label}',
                        icon='󰧑',
                        action_id=model_action,
                    ),
                )
                store.dispatch(
                    UpdateDynamicMenuAction(
                        menu_id=f'assistant:provider:{provider.name}',
                        title=provider.label,
                        heading=provider.label,
                        sub_heading='Manage this provider',
                        items=tuple(items),
                    ),
                )
                continue

            # "Select Model" — only when this engine is registered as an LLM
            # provider and exposes a curated model list.
            llm_name = _llm_name_for(provider)
            curated = getattr(provider, 'CURATED_MODELS', ())
            if llm_name is not None and curated:
                select_model_action = (
                    f'assistant:provider-detail:select-model:{provider.name}'
                )
                _provider_detail_action_ids.append(select_model_action)
                register_action(
                    select_model_action,
                    lambda ln=llm_name: store.dispatch(
                        StackPushMenuAction(menu_key=f'models:{ln.value}'),
                    ),
                    allow_reregister=True,
                )
                current_model = selected_models.get(
                    llm_name,
                    DEFAULT_MODELS.get(llm_name, ''),
                )
                items.append(
                    MenuItemData(
                        key='select-model',
                        label=f'Model: {current_model}',
                        icon='󰧑',
                        action_id=select_model_action,
                    ),
                )

            # The secrets file is the source of truth for whether credential
            # management options apply to this provider. Local engines such
            # as Piper / Vosk / local Ollama have no `credential_secret_ids`
            # so this is always False for them — no "Update Credentials" /
            # "Delete Credentials" items appear.
            if provider.has_stored_credentials():
                # "Update Credentials" — re-runs the setup flow
                setup_action = f'assistant:provider-detail:setup:{provider.name}'
                _provider_detail_action_ids.append(setup_action)
                register_action(
                    setup_action,
                    provider.setup,
                    allow_reregister=True,
                )
                items.append(
                    MenuItemData(
                        key='setup',
                        label='Update Credentials',
                        icon='󰒓',
                        action_id=setup_action,
                    ),
                )

                # "Delete Credentials" — push a confirmation prompt first.
                # The Yes button on the prompt invokes the actual clear action
                # which pops both the prompt and the provider-detail page so
                # the user lands back on the Manage Providers list.
                confirm_action = (
                    f'assistant:provider-detail:confirm-delete:{provider.name}'
                )
                _provider_detail_action_ids.append(confirm_action)

                def _make_confirm_delete_handler(
                    p: NeedsSetupMixin,
                ) -> Callable[[], None]:
                    def _handler() -> None:
                        p.clear_credentials()
                        # Pop prompt + provider-detail in one dispatch
                        store.dispatch(MenuGoBackAction(), MenuGoBackAction())

                    return _handler

                register_action(
                    confirm_action,
                    _make_confirm_delete_handler(provider),
                    allow_reregister=True,
                )

                delete_action = f'assistant:provider-detail:delete:{provider.name}'
                _provider_detail_action_ids.append(delete_action)

                def _make_delete_prompt_handler(
                    p: NeedsSetupMixin,
                    confirm_id: str,
                ) -> Callable[[], None]:
                    def _handler() -> None:
                        store.dispatch(
                            StackPushPromptAction(
                                title='Delete Credentials',
                                prompt=f'Forget {p.label} credentials?',
                                icon='󰆴',
                                items=(
                                    MenuItemData(
                                        key='yes',
                                        label='Delete',
                                        icon='󰆴',
                                        color=DANGER_COLOR,
                                        action_id=confirm_id,
                                    ),
                                    MenuItemData(
                                        key='cancel',
                                        label='Cancel',
                                        icon='󰜺',
                                        action_id='assistant:provider-detail:cancel',
                                    ),
                                ),
                            ),
                        )

                    return _handler

                register_action(
                    delete_action,
                    _make_delete_prompt_handler(provider, confirm_action),
                    allow_reregister=True,
                )
                items.append(
                    MenuItemData(
                        key='delete',
                        label='Delete Credentials',
                        icon='󰆴',
                        color=DANGER_COLOR,
                        action_id=delete_action,
                    ),
                )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'assistant:provider:{provider.name}',
                    title=provider.label,
                    heading=provider.label,
                    sub_heading='Manage this provider',
                    items=tuple(items),
                ),
            )

    @store.autorun(
        lambda state: (
            state.assistant.selected_stt,
            secrets_monitor.value,
            state.assistant.provider_setup_status,
        ),
    )
    def stt_providers(
        data: tuple[AssistantSTTName, dict[str, str | None], dict[str, bool]],
    ) -> None:
        """Update dynamic menu for STT engine selection."""
        from engine_menu_builder import build_engine_menu

        build_engine_menu(
            engines=STT_ENGINES,
            selected_name=data[0],
            menu_id='assistant:stt',
            title='Speech Recognition',
            action_prefix='stt',
            select_action_factory=lambda en: (
                lambda: store.dispatch(
                    AssistantSetSelectedSTTAction(
                        stt_name=AssistantSTTName(en),
                    ),
                )
            ),
            action_ids_list=_stt_action_ids,
        )

    @store.autorun(
        lambda state: (
            state.assistant.selected_llm,
            secrets_monitor.value,
            state.assistant.provider_setup_status,
        ),
    )
    def llm_providers(
        data: tuple[AssistantLLMName, dict[str, str | None], dict[str, bool]],
    ) -> None:
        """Update dynamic menu for LLM engine selection."""
        from engine_menu_builder import build_engine_menu

        build_engine_menu(
            engines=LLM_ENGINES,
            selected_name=data[0],
            menu_id='assistant:llm',
            title='Language Model',
            action_prefix='llm',
            select_action_factory=lambda en: (
                lambda: store.dispatch(
                    AssistantSetSelectedLLMAction(
                        llm_name=AssistantLLMName(en),
                    ),
                )
            ),
            action_ids_list=_llm_action_ids,
        )

    @store.autorun(
        lambda state: (
            state.assistant.selected_models,
            state.assistant.provider_setup_status,
        ),
    )
    def llm_model_pickers(
        data: tuple[dict[AssistantLLMName, str], dict[str, bool]],
    ) -> None:
        """Build per-provider model-selection submenus."""
        selected_models = data[0]

        for action_id in _llm_model_select_action_ids:
            unregister_action(action_id)
        _llm_model_select_action_ids.clear()

        for llm_name, engine in LLM_ENGINES.items():
            curated = getattr(engine, 'CURATED_MODELS', ())
            if not curated:
                continue

            selected_model = selected_models.get(
                llm_name,
                DEFAULT_MODELS.get(llm_name, ''),
            )

            options: list[tuple[str, str, str]] = []
            for model in curated:
                action_id = f'assistant:select-llm-model:{llm_name.value}:{model}'
                _llm_model_select_action_ids.append(action_id)
                register_action(
                    action_id,
                    lambda ln=llm_name, m=model: (
                        store.dispatch(
                            AssistantSetSelectedModelAction(
                                llm_name=ln,
                                model=m,
                            ),
                            MenuGoBackAction(),
                        )
                    ),
                    allow_reregister=True,
                )
                options.append((model, model, action_id))

            engine_label = getattr(engine, 'label', llm_name.value)
            build_selection_menu(
                options=options,
                selected_key=selected_model,
                menu_id=f'assistant:llm:models:{llm_name.value}',
                title='Select Model',
                heading=engine_label,
                sub_heading=f'Pick a model for {engine_label}.',
            )

    _ollama_categories_action_ids: list[str] = []
    _ollama_models_action_ids: list[str] = []

    @store.autorun(
        lambda state: state.assistant.selected_models.get(
            AssistantLLMName.OLLAMA,
            DEFAULT_LLM_OLLAMA_MODEL,
        ),
    )
    def ollama_categories_menu(current_model: str) -> None:
        """Build the top-level Ollama category list."""
        from ubo_app.engines.ollama_catalog import category_of

        # Whenever the selection changes (and once at startup), kick off a
        # capability probe for the active model so the "Thinking: On/Off"
        # item appears for models that advertise it. The probe is no-op if
        # the daemon is down or the model isn't downloaded yet. Same pass
        # also refreshes the cached downloaded-models set so the catalog
        # dot indicator picks up any pulls made outside the app (e.g. via
        # `ollama pull` from a shell).
        engine = LLM_ENGINES.get(AssistantLLMName.OLLAMA)
        if isinstance(engine, OllamaEngine):
            create_task(engine._probe_and_dispatch_capabilities(current_model))  # noqa: SLF001
            create_task(engine.refresh_downloaded_models())

        for action_id in _ollama_categories_action_ids:
            unregister_action(action_id)
        _ollama_categories_action_ids.clear()

        selected_category = category_of(current_model)
        items: list[MenuItemData] = []

        for category in OLLAMA_CATALOG:
            action_id = (
                f'assistant:ollama:open-category:{category.id}'
            )
            _ollama_categories_action_ids.append(action_id)
            register_action(
                action_id,
                lambda cid=category.id: store.dispatch(
                    StackPushMenuAction(menu_key=f'ollama:models:{cid}'),
                ),
                allow_reregister=True,
            )
            is_current = (
                selected_category is not None
                and selected_category.id == category.id
            )
            items.append(
                MenuItemData(
                    key=category.id,
                    label=category.label,
                    icon='󰄬' if is_current else '󰍳',
                    background_color=INFO_COLOR if is_current else None,
                    action_id=action_id,
                ),
            )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:ollama:categories',
                title='Ollama Models',
                heading='Ollama',
                sub_heading='Pick a model family',
                items=tuple(items),
            ),
        )

    @store.autorun(
        lambda state: (
            state.assistant.selected_models.get(
                AssistantLLMName.OLLAMA,
                DEFAULT_LLM_OLLAMA_MODEL,
            ),
            state.assistant.ollama_downloaded_models,
        ),
    )
    def ollama_models_menus(data: tuple[str, tuple[str, ...]]) -> None:
        """Build a per-category Ollama model submenu with RAM gating.

        Reads ``ollama_downloaded_models`` from cached state — never calls the
        Ollama daemon synchronously, since this autorun fires on the redux
        dispatch path and any HTTP latency here would freeze menu rendering.
        ``OllamaEngine.refresh_downloaded_models`` is what keeps the cache
        warm (kicked off from ``init_service``, after every download, and from
        ``ollama_categories_menu`` so user-driven navigation gets fresh data).
        """
        current_model, downloaded_models = data

        for action_id in _ollama_models_action_ids:
            unregister_action(action_id)
        _ollama_models_action_ids.clear()

        total_ram = _total_ram_bytes()

        for category in OLLAMA_CATALOG:
            items: list[MenuItemData] = []
            for entry in category.models:
                feasible = total_ram == 0 or fits_in_ram(entry, total_ram)
                is_downloaded = (
                    normalize_model_tag(entry.id) in downloaded_models
                )
                is_selected = entry.id == current_model
                label = f'{entry.label}  {format_size(entry.size_bytes)}'
                if is_downloaded and not is_selected:
                    label = f'{label}  •'

                if feasible:
                    action_id = (
                        f'assistant:ollama:select-model:{entry.id}'
                    )
                    _ollama_models_action_ids.append(action_id)

                    def _make_select_handler(
                        mid: str,
                        *,
                        downloaded: bool,
                    ) -> Callable[[], None]:
                        def _handler() -> None:
                            if downloaded:
                                store.dispatch(
                                    AssistantSetSelectedModelAction(
                                        llm_name=AssistantLLMName.OLLAMA,
                                        model=mid,
                                    ),
                                    MenuGoBackAction(),
                                    MenuGoBackAction(),
                                )
                            else:
                                store.dispatch(
                                    AssistantDownloadOllamaModelAction(
                                        model=mid,
                                    ),
                                    MenuGoBackAction(),
                                    MenuGoBackAction(),
                                )

                        return _handler

                    register_action(
                        action_id,
                        _make_select_handler(
                            entry.id,
                            downloaded=is_downloaded,
                        ),
                        allow_reregister=True,
                    )
                    items.append(
                        MenuItemData(
                            key=entry.id,
                            label=label,
                            icon='󰄬' if is_selected else (
                                '󰇚' if not is_downloaded else '󰧑'
                            ),
                            background_color=(
                                INFO_COLOR if is_selected else None
                            ),
                            action_id=action_id,
                        ),
                    )
                else:
                    required_gb = _format_ram_gb(required_ram_bytes(entry))
                    total_gb = _format_ram_gb(total_ram) if total_ram else 'unknown'
                    disabled_action = (
                        f'assistant:ollama:ram-limit:{entry.id}'
                    )
                    _ollama_models_action_ids.append(disabled_action)
                    register_action(
                        disabled_action,
                        lambda mid=entry.id, req=required_gb, tot=total_gb: (
                            store.dispatch(
                                NotificationsAddAction(
                                    notification=Notification(
                                        id=OLLAMA_RAM_LIMIT_NOTIFICATION_ID,
                                        title='Insufficient RAM',
                                        content=(
                                            f'Cannot run {mid}. '
                                            f'Needs ~{req} free RAM, '
                                            f'device has {tot} total.'
                                        ),
                                        icon='󰀦',
                                        color=WARNING_COLOR,
                                        display_type=(
                                            NotificationDisplayType.FLASH
                                        ),
                                    ),
                                ),
                            )
                        ),
                        allow_reregister=True,
                    )
                    items.append(
                        MenuItemData(
                            key=entry.id,
                            label=label,
                            icon='󰗖',
                            color='#666666',
                            action_id=disabled_action,
                        ),
                    )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'assistant:ollama:models:{category.id}',
                    title=category.label,
                    heading=category.label,
                    sub_heading=(
                        f'Device RAM: {_format_ram_gb(total_ram)}'
                        if total_ram
                        else 'Pick a model'
                    ),
                    items=tuple(items),
                ),
            )

    def _handle_ollama_download(event: AssistantDownloadOllamaModelEvent) -> None:
        """Run the local Ollama download flow for the requested model."""
        engine = LLM_ENGINES.get(AssistantLLMName.OLLAMA)
        if isinstance(engine, OllamaEngine):
            engine.download_model(event.model)

    _piper_language_action_ids: list[str] = []
    _piper_voice_action_ids: list[str] = []

    def _piper_engine() -> PiperEngine | None:
        engine = TTS_ENGINES.get(AssistantTTSName.PIPER)
        return engine if isinstance(engine, PiperEngine) else None

    @store.autorun(
        lambda state: (
            state.assistant.selected_piper_voice,
            state.localization.language,
        ),
    )
    def piper_languages_menu(
        data: tuple[str, LanguageCode],
    ) -> None:
        """Build the Piper language picker (English + system language)."""
        selected_voice, system_language = data
        selected_voice = selected_voice or DEFAULT_PIPER_VOICE_ID

        for action_id in _piper_language_action_ids:
            unregister_action(action_id)
        _piper_language_action_ids.clear()

        # Refresh the downloaded-voices cache so the per-voice indicators
        # are accurate. No-op when nothing changed (set comparison).
        engine = _piper_engine()
        if engine is not None:
            create_task(engine.refresh_downloaded_voices())

        current_language = language_for(selected_voice)
        languages = visible_languages(system_language)
        items: list[MenuItemData] = []
        for language in languages:
            action_id = f'assistant:piper:open-language:{language.code.value}'
            _piper_language_action_ids.append(action_id)
            register_action(
                action_id,
                lambda code=language.code: store.dispatch(
                    StackPushMenuAction(
                        menu_key=f'piper:voices:{code.value}',
                    ),
                ),
                allow_reregister=True,
            )
            is_current = (
                current_language is not None
                and current_language.code == language.code
            )
            items.append(
                MenuItemData(
                    key=language.code.value,
                    label=language.label,
                    icon='󰄬' if is_current else '󰗊',
                    background_color=INFO_COLOR if is_current else None,
                    action_id=action_id,
                ),
            )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:piper:languages',
                title='Piper Languages',
                heading='Piper',
                sub_heading='Pick a language',
                items=tuple(items),
            ),
        )

    @store.autorun(
        lambda state: (
            state.assistant.selected_piper_voice,
            state.assistant.piper_downloaded_voices,
        ),
    )
    def piper_voices_menus(data: tuple[str, tuple[str, ...]]) -> None:
        """Build per-language Piper voice submenus."""
        selected_voice, downloaded_voices = data
        selected_voice = selected_voice or DEFAULT_PIPER_VOICE_ID
        downloaded_set = set(downloaded_voices)

        for action_id in _piper_voice_action_ids:
            unregister_action(action_id)
        _piper_voice_action_ids.clear()

        def _make_voice_handler(
            voice_id: str,
            *,
            downloaded: bool,
        ) -> Callable[[], None]:
            def _handler() -> None:
                if downloaded:
                    store.dispatch(
                        AssistantSetSelectedPiperVoiceAction(voice_id=voice_id),
                        MenuGoBackAction(),
                        MenuGoBackAction(),
                    )
                else:
                    store.dispatch(
                        AssistantSetSelectedPiperVoiceAction(voice_id=voice_id),
                        AssistantDownloadPiperVoiceAction(voice_id=voice_id),
                        MenuGoBackAction(),
                        MenuGoBackAction(),
                    )

            return _handler

        for language in PIPER_LANGUAGES:
            items: list[MenuItemData] = []
            for voice in language.voices:
                is_selected = voice.id == selected_voice
                is_downloaded = voice.id in downloaded_set
                label = voice_label(voice)
                if is_downloaded and not is_selected:
                    label = f'{label}  •'

                action_id = f'assistant:piper:select-voice:{voice.id}'
                _piper_voice_action_ids.append(action_id)
                register_action(
                    action_id,
                    _make_voice_handler(voice.id, downloaded=is_downloaded),
                    allow_reregister=True,
                )

                items.append(
                    MenuItemData(
                        key=voice.id,
                        label=label,
                        icon='󰄬' if is_selected else (
                            '󰇚' if not is_downloaded else '󰔊'
                        ),
                        background_color=(
                            INFO_COLOR if is_selected else None
                        ),
                        action_id=action_id,
                    ),
                )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'assistant:piper:voices:{language.code.value}',
                    title=language.label,
                    heading=language.label,
                    sub_heading='Pick a voice',
                    items=tuple(items),
                ),
            )

    def _handle_piper_download(event: AssistantDownloadPiperVoiceEvent) -> None:
        """Run the Piper download flow for the requested voice."""
        engine = _piper_engine()
        if engine is not None:
            engine.download_voice(event.voice_id)

    _kokoro_language_action_ids: list[str] = []
    _kokoro_voice_action_ids: list[str] = []

    def _kokoro_engine() -> KokoroEngine | None:
        engine = TTS_ENGINES.get(AssistantTTSName.KOKORO)
        return engine if isinstance(engine, KokoroEngine) else None

    @store.autorun(
        lambda state: (
            state.assistant.selected_kokoro_voice,
            state.localization.language,
        ),
    )
    def kokoro_languages_menu(
        data: tuple[str, LanguageCode],
    ) -> None:
        """Build the Kokoro language picker (English + system language)."""
        selected_voice, system_language = data
        selected_voice = selected_voice or DEFAULT_KOKORO_VOICE_ID

        for action_id in _kokoro_language_action_ids:
            unregister_action(action_id)
        _kokoro_language_action_ids.clear()

        # Refresh the cached download flag so the per-voice indicators
        # render correctly when the bundle was already on disk from a
        # previous session.
        engine = _kokoro_engine()
        if engine is not None:
            create_task(engine.refresh_downloaded_state())

        current_language = kokoro_language_for(selected_voice)
        languages = kokoro_visible_languages(system_language)
        items: list[MenuItemData] = []
        for language in languages:
            action_id = f'assistant:kokoro:open-language:{language.code.value}'
            _kokoro_language_action_ids.append(action_id)
            register_action(
                action_id,
                lambda code=language.code: store.dispatch(
                    StackPushMenuAction(
                        menu_key=f'kokoro:voices:{code.value}',
                    ),
                ),
                allow_reregister=True,
            )
            is_current = (
                current_language is not None
                and current_language.code == language.code
            )
            items.append(
                MenuItemData(
                    key=language.code.value,
                    label=language.label,
                    icon='󰄬' if is_current else '󰗊',
                    background_color=INFO_COLOR if is_current else None,
                    action_id=action_id,
                ),
            )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:kokoro:languages',
                title='Kokoro Languages',
                heading='Kokoro',
                sub_heading='Pick a language',
                items=tuple(items),
            ),
        )

    @store.autorun(
        lambda state: (
            state.assistant.selected_kokoro_voice,
            state.assistant.kokoro_is_downloaded,
        ),
    )
    def kokoro_voices_menus(data: tuple[str, bool]) -> None:
        """Build per-language Kokoro voice submenus.

        Kokoro bundles every voice in a single file pair, so the
        ``downloaded`` indicator is the same across all voices: either
        all are available (after the first download) or none are.
        """
        selected_voice, is_downloaded = data
        selected_voice = selected_voice or DEFAULT_KOKORO_VOICE_ID

        for action_id in _kokoro_voice_action_ids:
            unregister_action(action_id)
        _kokoro_voice_action_ids.clear()

        def _make_voice_handler(
            voice_id: str,
            *,
            downloaded: bool,
        ) -> Callable[[], None]:
            def _handler() -> None:
                if downloaded:
                    store.dispatch(
                        AssistantSetSelectedKokoroVoiceAction(voice_id=voice_id),
                        MenuGoBackAction(),
                        MenuGoBackAction(),
                    )
                else:
                    store.dispatch(
                        AssistantSetSelectedKokoroVoiceAction(voice_id=voice_id),
                        AssistantDownloadKokoroAction(voice_id=voice_id),
                        MenuGoBackAction(),
                        MenuGoBackAction(),
                    )

            return _handler

        for language in KOKORO_LANGUAGES:
            items: list[MenuItemData] = []
            for voice in language.voices:
                is_selected = voice.id == selected_voice
                label = kokoro_voice_label(voice)
                if is_downloaded and not is_selected:
                    label = f'{label}  •'

                action_id = f'assistant:kokoro:select-voice:{voice.id}'
                _kokoro_voice_action_ids.append(action_id)
                register_action(
                    action_id,
                    _make_voice_handler(voice.id, downloaded=is_downloaded),
                    allow_reregister=True,
                )

                items.append(
                    MenuItemData(
                        key=voice.id,
                        label=label,
                        icon='󰄬' if is_selected else (
                            '󰇚' if not is_downloaded else '󰔊'
                        ),
                        background_color=(
                            INFO_COLOR if is_selected else None
                        ),
                        action_id=action_id,
                    ),
                )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'assistant:kokoro:voices:{language.code.value}',
                    title=language.label,
                    heading=language.label,
                    sub_heading='Pick a voice',
                    items=tuple(items),
                ),
            )

    def _handle_kokoro_download(event: AssistantDownloadKokoroEvent) -> None:
        """Run the Kokoro bundle download flow."""
        engine = _kokoro_engine()
        if engine is not None:
            engine.download_voice(event.voice_id)

    _vosk_language_action_ids: list[str] = []
    _vosk_model_action_ids: list[str] = []

    def _vosk_engine() -> VoskEngine | None:
        engine = STT_ENGINES.get(AssistantSTTName.VOSK)
        return engine if isinstance(engine, VoskEngine) else None

    @store.autorun(
        lambda state: (
            state.assistant.selected_vosk_model,
            state.localization.language,
        ),
    )
    def vosk_languages_menu(
        data: tuple[str, LanguageCode],
    ) -> None:
        """Build the Vosk language picker (English + system language)."""
        selected_model, system_language = data
        selected_model = selected_model or DEFAULT_VOSK_MODEL_ID

        for action_id in _vosk_language_action_ids:
            unregister_action(action_id)
        _vosk_language_action_ids.clear()

        # Refresh the downloaded-models cache so per-model indicators are
        # accurate. No-op when nothing changed (set comparison).
        engine = _vosk_engine()
        if engine is not None:
            create_task(engine.refresh_downloaded_models())

        current_language = vosk_language_for(selected_model)
        languages = vosk_visible_languages(system_language)
        items: list[MenuItemData] = []
        for language in languages:
            action_id = f'assistant:vosk:open-language:{language.code.value}'
            _vosk_language_action_ids.append(action_id)
            register_action(
                action_id,
                lambda code=language.code: store.dispatch(
                    StackPushMenuAction(
                        menu_key=f'vosk:models:{code.value}',
                    ),
                ),
                allow_reregister=True,
            )
            is_current = (
                current_language is not None
                and current_language.code == language.code
            )
            items.append(
                MenuItemData(
                    key=language.code.value,
                    label=language.label,
                    icon='󰄬' if is_current else '󰗊',
                    background_color=INFO_COLOR if is_current else None,
                    action_id=action_id,
                ),
            )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:vosk:languages',
                title='Vosk Languages',
                heading='Vosk',
                sub_heading='Pick a language',
                items=tuple(items),
            ),
        )

    @store.autorun(
        lambda state: (
            state.assistant.selected_vosk_model,
            state.assistant.vosk_downloaded_models,
        ),
    )
    def vosk_models_menus(data: tuple[str, tuple[str, ...]]) -> None:
        """Build per-language Vosk model submenus."""
        selected_model, downloaded_models = data
        selected_model = selected_model or DEFAULT_VOSK_MODEL_ID
        downloaded_set = set(downloaded_models)

        for action_id in _vosk_model_action_ids:
            unregister_action(action_id)
        _vosk_model_action_ids.clear()

        def _make_model_handler(
            model_id: str,
            *,
            downloaded: bool,
        ) -> Callable[[], None]:
            def _handler() -> None:
                if downloaded:
                    store.dispatch(
                        AssistantSetSelectedVoskModelAction(model_id=model_id),
                        MenuGoBackAction(),
                        MenuGoBackAction(),
                    )
                else:
                    store.dispatch(
                        AssistantSetSelectedVoskModelAction(model_id=model_id),
                        AssistantDownloadVoskModelAction(model_id=model_id),
                        MenuGoBackAction(),
                        MenuGoBackAction(),
                    )

            return _handler

        for language in VOSK_LANGUAGES:
            items: list[MenuItemData] = []
            for model in language.models:
                is_selected = model.id == selected_model
                is_downloaded = model.id in downloaded_set
                label = vosk_model_label(model)
                if is_downloaded and not is_selected:
                    label = f'{label}  •'

                action_id = f'assistant:vosk:select-model:{model.id}'
                _vosk_model_action_ids.append(action_id)
                register_action(
                    action_id,
                    _make_model_handler(model.id, downloaded=is_downloaded),
                    allow_reregister=True,
                )

                items.append(
                    MenuItemData(
                        key=model.id,
                        label=label,
                        icon='󰄬' if is_selected else (
                            '󰇚' if not is_downloaded else '󰧑'
                        ),
                        background_color=(
                            INFO_COLOR if is_selected else None
                        ),
                        action_id=action_id,
                    ),
                )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'assistant:vosk:models:{language.code.value}',
                    title=language.label,
                    heading=language.label,
                    sub_heading='Pick a model',
                    items=tuple(items),
                ),
            )

    def _handle_vosk_download(event: AssistantDownloadVoskModelEvent) -> None:
        """Run the Vosk download flow for the requested model."""
        engine = _vosk_engine()
        if engine is not None:
            engine.download_model(event.model_id)

    @store.autorun(
        lambda state: (
            state.assistant.selected_tts,
            secrets_monitor.value,
            state.assistant.provider_setup_status,
        ),
    )
    def tts_providers(
        data: tuple[AssistantTTSName, dict[str, str | None], dict[str, bool]],
    ) -> None:
        """Update dynamic menu for TTS engine selection."""
        from engine_menu_builder import build_engine_menu

        build_engine_menu(
            engines=TTS_ENGINES,
            selected_name=data[0],
            menu_id='assistant:tts',
            title='Speech Synthesis',
            action_prefix='tts',
            select_action_factory=lambda en: (
                lambda: store.dispatch(
                    AssistantSetSelectedTTSAction(
                        tts_name=AssistantTTSName(en),
                    ),
                )
            ),
            action_ids_list=_tts_action_ids,
        )

    @store.autorun(
        lambda state: (
            state.assistant.selected_image_generator,
            secrets_monitor.value,
            state.assistant.provider_setup_status,
        ),
    )
    def image_generator_providers(
        data: tuple[
            AssistantImageGeneratorName,
            dict[str, str | None],
            dict[str, bool],
        ],
    ) -> None:
        """Update dynamic menu for image generator engine selection."""
        from engine_menu_builder import build_engine_menu

        build_engine_menu(
            engines=IMAGE_GENERATOR_ENGINES,
            selected_name=data[0],
            menu_id='assistant:image_generator',
            title='Image Generator',
            action_prefix='img-gen',
            select_action_factory=lambda en: (
                lambda: store.dispatch(
                    AssistantSetSelectedImageGeneratorAction(
                        image_generator_name=AssistantImageGeneratorName(en),
                    ),
                )
            ),
            action_ids_list=_img_gen_action_ids,
        )

    # MCP Tools menu - main list
    @store.autorun(
        lambda state: (
            state.assistant.mcp_servers,
            state.assistant.enabled_mcp_servers,
        ),
    )
    def mcp_servers_menu(
        state_data: tuple[dict[str, McpServerMetadata], list[str]],
    ) -> None:
        """Update dynamic menu for MCP servers."""
        loaded_servers, enabled_servers = state_data

        for action_id in _mcp_action_ids:
            unregister_action(action_id)
        _mcp_action_ids.clear()

        logger.debug(
            'MCP servers menu autorun triggered',
            extra={
                'server_count': len(loaded_servers),
                'server_ids': list(loaded_servers.keys()),
                'enabled_count': len(enabled_servers),
            },
        )

        add_action_id = 'assistant:add-mcp-server'
        _mcp_action_ids.append(add_action_id)
        register_action(add_action_id, input_mcp_server)

        items: list[MenuItemData] = [
            MenuItemData(
                key='add_server',
                label='Add Server',
                icon='󰌉',
                action_id=add_action_id,
            ),
        ]

        # Clean up autoruns for servers no longer in the list
        removed_ids = set(_mcp_server_unsubscribers.keys()) - set(
            loaded_servers.keys(),
        )
        for removed_id in removed_ids:
            _mcp_server_unsubscribers.pop(removed_id)()

        for server_id, server in loaded_servers.items():
            is_enabled = server_id in enabled_servers
            open_action_id = f'assistant:open-mcp:{server_id}'
            _mcp_action_ids.append(open_action_id)
            register_action(
                open_action_id,
                lambda _sid=server_id: store.dispatch(
                    StackPushMenuAction(menu_key=_sid),
                ),
            )
            items.append(
                MenuItemData(
                    key=server_id,
                    label=server.name,
                    icon='󰄬' if is_enabled else '󰖭',
                    background_color=INFO_COLOR if is_enabled else WARNING_COLOR,
                    action_id=open_action_id,
                ),
            )

            # Set up the detail menu for this server (only if not already tracked)
            if server_id not in _mcp_server_unsubscribers:
                _mcp_server_unsubscribers[server_id] = mcp_server_menu(server_id)

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:mcp_tools',
                title='MCP Tools',
                heading='Model Context Protocol Tools',
                sub_heading='Add and manage MCP servers',
                items=tuple(items),
            ),
        )

    def mcp_server_menu(server_id: str) -> Callable:
        """Set up dynamic menu updates for a specific MCP server."""
        from ubo_app.store.services.assistant import (
            AssistantDeleteMcpServerAction,
            AssistantToggleMcpServerAction,
        )

        _server_action_ids: list[str] = []

        @store.autorun(
            lambda state: (
                state.assistant.mcp_servers.get(server_id),
                server_id in state.assistant.enabled_mcp_servers,
            ),
            options=AutorunOptions(default_value=None),
        )
        def menu(
            state_data: tuple[McpServerMetadata | None, bool],
        ) -> None:
            server, is_enabled = state_data

            for action_id in _server_action_ids:
                unregister_action(action_id)
            _server_action_ids.clear()

            if not server:
                store.dispatch(
                    UpdateDynamicMenuAction(
                        menu_id=f'assistant:mcp:{server_id}',
                        title='MCP Server',
                        items=(),
                        heading='Server Not Found',
                    ),
                )
                return

            toggle_action_id = f'assistant:toggle-mcp:{server_id}'
            _server_action_ids.append(toggle_action_id)
            register_action(
                toggle_action_id,
                lambda: store.dispatch(
                    AssistantToggleMcpServerAction(server_id=server_id),
                ),
            )

            delete_action_id = f'assistant:delete-mcp:{server_id}'
            _server_action_ids.append(delete_action_id)
            register_action(
                delete_action_id,
                lambda: store.dispatch(
                    AssistantDeleteMcpServerAction(server_id=server_id),
                ),
            )

            status_text = 'Enabled' if is_enabled else 'Disabled'
            items = (
                MenuItemData(
                    key='toggle',
                    label='Disable' if is_enabled else 'Enable',
                    icon='󰖭' if is_enabled else '󰄬',
                    background_color=WARNING_COLOR if is_enabled else INFO_COLOR,
                    action_id=toggle_action_id,
                ),
                MenuItemData(
                    key='delete',
                    label='Delete',
                    icon='󰆴',
                    background_color=DANGER_COLOR,
                    action_id=delete_action_id,
                ),
            )

            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'assistant:mcp:{server_id}',
                    title=f'MCP: {server.name}',
                    items=items,
                    heading=server.name,
                    sub_heading=f'Type: {server.type} • {status_text}',
                ),
            )

        return menu.unsubscribe

    # Event handlers for MCP servers
    def handle_add_mcp_server(_event: AssistantAddMcpServerEvent) -> None:
        """Handle MCP server add event."""
        # Trigger sync to reload from filesystem
        logger.info('handle_add_mcp_server invoked, dispatching sync')
        store.dispatch(
            AssistantSyncMcpServersAction(),
        )

    def handle_delete_mcp_server(event: AssistantDeleteMcpServerEvent) -> None:
        """Handle MCP server delete event."""
        from mcp_servers import delete_mcp_server

        logger.info(
            'handle_delete_mcp_server invoked',
            extra={'server_id': event.server_id},
        )
        delete_mcp_server(event.server_id)
        # Navigate back to server list
        store.dispatch(MenuGoBackAction())
        # Trigger sync to update state
        logger.info('Dispatching AssistantSyncMcpServersAction after delete')
        store.dispatch(AssistantSyncMcpServersAction())

    def handle_toggle_mcp_server(event: AssistantToggleMcpServerEvent) -> None:
        """Persist the toggled MCP server enabled state to the filesystem."""
        from mcp_servers import toggle_mcp_server

        logger.info(
            'handle_toggle_mcp_server invoked',
            extra={'server_id': event.server_id},
        )
        toggle_mcp_server(event.server_id)

    def handle_sync_mcp_servers(_event: AssistantSyncMcpServersEvent) -> None:
        """Load MCP servers from the filesystem and push them into the store."""
        from mcp_servers import load_enabled_mcp_server_ids, load_mcp_servers

        servers = load_mcp_servers()
        enabled = load_enabled_mcp_server_ids()
        logger.info(
            'handle_sync_mcp_servers loaded servers',
            extra={'count': len(servers), 'enabled': len(enabled)},
        )
        store.dispatch(
            AssistantSetMcpServersAction(
                servers=list(servers.values()),
                enabled_servers=enabled,
            ),
        )

    return (
        secrets_monitor,
        providers,
        provider_details,
        stt_providers,
        llm_providers,
        llm_model_pickers,
        ollama_categories_menu,
        ollama_models_menus,
        piper_languages_menu,
        piper_voices_menus,
        kokoro_languages_menu,
        kokoro_voices_menus,
        vosk_languages_menu,
        vosk_models_menus,
        tts_providers,
        image_generator_providers,
        mcp_servers_menu,
        handle_add_mcp_server,
        handle_delete_mcp_server,
        handle_toggle_mcp_server,
        handle_sync_mcp_servers,
        _handle_ollama_download,
        _handle_piper_download,
        _handle_kokoro_download,
        _handle_vosk_download,
    )


def _register_assistant_path_matchers() -> None:  # noqa: C901
    """Register path matchers for assistant sub-pages."""
    from ubo_app.store.core.view_registry import register_path_menu_matcher

    # Map assistant menu keys to dynamic menu IDs
    assistant_menus = {
        'assistant:providers': 'assistant:providers',
        'assistant:stt': 'assistant:stt',
        'assistant:llm': 'assistant:llm',
        'assistant:tts': 'assistant:tts',
        'assistant:image_generator': 'assistant:image_generator',
        'assistant:mcp_tools': 'assistant:mcp_tools',
    }

    def _match_catalog_tail(tail: str) -> str | None:
        """Leaf segments owned by Ollama / Piper / Kokoro / Vosk drill-downs."""
        if tail == 'ollama:categories':
            return 'assistant:ollama:categories'
        if tail.startswith('ollama:models:'):
            return f'assistant:ollama:models:{tail[len("ollama:models:") :]}'
        if tail == 'piper:languages':
            return 'assistant:piper:languages'
        if tail.startswith('piper:voices:'):
            return f'assistant:piper:voices:{tail[len("piper:voices:") :]}'
        if tail == 'kokoro:languages':
            return 'assistant:kokoro:languages'
        if tail.startswith('kokoro:voices:'):
            return f'assistant:kokoro:voices:{tail[len("kokoro:voices:") :]}'
        if tail == 'vosk:languages':
            return 'assistant:vosk:languages'
        if tail.startswith('vosk:models:'):
            return f'assistant:vosk:models:{tail[len("vosk:models:") :]}'
        return None

    def _assistant_path_matcher(path: tuple[str, ...]) -> str | None:
        # Paths like ('main', 'settings', 'Assistant', 'assistant:stt')
        if (
            len(path) >= 4  # noqa: PLR2004
            and path[:3] == ('main', 'settings', 'Assistant')
        ):
            menu_key = path[3]
            catalog = _match_catalog_tail(path[-1])
            if catalog is not None:
                return catalog
            # Generic "models:<provider>" tail — reached from anywhere under
            # Assistant (LLM menu, Manage Providers detail, etc.).
            if len(path) >= 5 and path[-1].startswith('models:'):  # noqa: PLR2004
                provider = path[-1][len('models:') :]
                return f'assistant:llm:models:{provider}'
            # MCP server detail pages must be checked BEFORE the general
            # assistant_menus lookup, otherwise 'assistant:mcp_tools' matches
            # the list menu and the detail path is never reached.
            # Path: ('main', 'settings', 'Assistant',
            #   'assistant:mcp_tools', '{server_id}')
            if len(path) >= 5 and menu_key == 'assistant:mcp_tools':  # noqa: PLR2004
                server_id = path[4]
                return f'assistant:mcp:{server_id}'
            # Provider detail page reached from Manage Providers.
            # Path: ('main', 'settings', 'Assistant', 'assistant:providers',
            #   'provider:{name}')
            if (
                len(path) >= 5  # noqa: PLR2004
                and menu_key == 'assistant:providers'
                and path[4].startswith('provider:')
            ):
                provider_name = path[4][len('provider:') :]
                return f'assistant:provider:{provider_name}'
            if menu_key in assistant_menus:
                return assistant_menus[menu_key]
        return None

    register_path_menu_matcher('assistant:menus', _assistant_path_matcher)


async def init_service() -> None:
    """Initialize the assistant service."""
    _register_persistent_stores()

    # Register view dependencies for menu content updates
    register_menu_content_dependency(
        'assistant:stt',
        lambda s: s.assistant.selected_stt,
    )
    register_menu_content_dependency(
        'assistant:llm',
        lambda s: s.assistant.selected_llm,
    )
    # Model picker submenus depend on the user's per-provider selection
    for _llm_name in LLM_ENGINES:
        register_menu_content_dependency(
            f'assistant:llm:models:{_llm_name.value}',
            lambda s, ln=_llm_name: s.assistant.selected_models.get(ln, ''),
        )
    # Provider-detail menus depend on the provider's setup status (so the
    # "Update" / "Delete" rows refresh) and the active model for the
    # "Model: <current>" line when the provider is also an LLM. Changes to
    # the secrets file are captured by the `provider_details` autorun (which
    # keys on `secrets_monitor.value` and re-dispatches the dynamic menu),
    # so we don't probe the filesystem here on every state tick.
    _dedup_engines: dict[type, AIProviderMixin] = {
        type(engine): engine
        for engine in {
            *STT_ENGINES.values(),
            *LLM_ENGINES.values(),
            *TTS_ENGINES.values(),
            *IMAGE_GENERATOR_ENGINES.values(),
        }
        if engine is not None and isinstance(engine, NeedsSetupMixin)
    }
    for _engine in _dedup_engines.values():
        register_menu_content_dependency(
            f'assistant:provider:{_engine.name}',
            lambda s, e=_engine: (
                s.assistant.provider_setup_status.get(str(e.name), False),
                tuple(sorted(s.assistant.selected_models.items())),
                tuple(sorted(s.assistant.ollama_thinking_enabled.items())),
                tuple(sorted(s.assistant.ollama_model_capabilities.items())),
                s.assistant.selected_piper_voice,
                s.assistant.selected_kokoro_voice,
            ),
        )
    # Ollama categorised picker depends on the current selection so the
    # checkmark on the current category re-renders when the user picks a new
    # model.
    register_menu_content_dependency(
        'assistant:ollama:categories',
        lambda s: s.assistant.selected_models.get(
            AssistantLLMName.OLLAMA,
            '',
        ),
    )
    for _category in OLLAMA_CATALOG:
        register_menu_content_dependency(
            f'assistant:ollama:models:{_category.id}',
            lambda s: s.assistant.selected_models.get(
                AssistantLLMName.OLLAMA,
                '',
            ),
        )
    register_menu_content_dependency(
        'assistant:tts',
        lambda s: s.assistant.selected_tts,
    )
    # Piper picker depends on the current voice selection (for the
    # checkmark) and on the system language (for which non-English
    # languages are visible in the picker).
    register_menu_content_dependency(
        'assistant:piper:languages',
        lambda s: (
            s.assistant.selected_piper_voice,
            s.localization.language,
        ),
    )
    for _language in PIPER_LANGUAGES:
        register_menu_content_dependency(
            f'assistant:piper:voices:{_language.code.value}',
            lambda s: (
                s.assistant.selected_piper_voice,
                tuple(s.assistant.piper_downloaded_voices),
            ),
        )
    # Kokoro mirrors the Piper picker: language menu depends on the
    # current voice (for the checkmark) and the system language (for
    # which non-English languages are visible); each per-language voice
    # menu depends on the current voice and the single
    # ``kokoro_is_downloaded`` flag (the bundle is all-or-nothing).
    register_menu_content_dependency(
        'assistant:kokoro:languages',
        lambda s: (
            s.assistant.selected_kokoro_voice,
            s.localization.language,
        ),
    )
    for _kokoro_lang in KOKORO_LANGUAGES:
        register_menu_content_dependency(
            f'assistant:kokoro:voices:{_kokoro_lang.code.value}',
            lambda s: (
                s.assistant.selected_kokoro_voice,
                s.assistant.kokoro_is_downloaded,
            ),
        )
    register_menu_content_dependency(
        'assistant:image_gen',
        lambda s: s.assistant.selected_image_generator,
    )
    register_menu_content_dependency(
        'assistant:mcp_enabled',
        lambda s: tuple(s.assistant.enabled_mcp_servers),
    )
    register_menu_content_dependency(
        'assistant:mcp_servers',
        lambda s: tuple(s.assistant.mcp_servers.keys()),
    )
    register_menu_content_dependency(
        'assistant:provider_status',
        lambda s: tuple(s.assistant.provider_setup_status.items()),
    )

    (
        _secrets_monitor,
        _providers,
        _provider_details,
        _stt_providers,
        _llm_providers,
        _llm_model_pickers,
        _ollama_categories_menu,
        _ollama_models_menus,
        _piper_languages_menu,
        _piper_voices_menus,
        _kokoro_languages_menu,
        _kokoro_voices_menus,
        _vosk_languages_menu,
        _vosk_models_menus,
        _tts_providers,
        _image_generator_providers,
        _mcp_servers_menu,
        handle_add_mcp_server,
        handle_delete_mcp_server,
        handle_toggle_mcp_server,
        handle_sync_mcp_servers,
        handle_ollama_download,
        handle_piper_download,
        handle_kokoro_download,
        handle_vosk_download,
    ) = _setup_autorun_and_handlers()

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=10,
            key='providers',
            label='Manage',
            icon='󰶗',
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=50,
            key='stt',
            label='Speech Recognition',
            icon='',
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=40,
            key='llm',
            label='Language Model',
            icon='󰁤',
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=30,
            key='tts',
            label='Speech Synthesis',
            icon='󰔊',
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=20,
            key='image_generator',
            label='Image Generator',
            icon='󰹉',
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=15,
            key='mcp_tools',
            label='MCP Tools',
            icon='󰒋',
        ),
    )

    # Register path matchers for assistant sub-pages
    _register_assistant_path_matchers()

    store.subscribe_event(AssistantHandleReportEvent, _communicate)
    store.subscribe_event(AssistantAddMcpServerEvent, handle_add_mcp_server)
    store.subscribe_event(AssistantDeleteMcpServerEvent, handle_delete_mcp_server)
    store.subscribe_event(AssistantToggleMcpServerEvent, handle_toggle_mcp_server)
    store.subscribe_event(AssistantSyncMcpServersEvent, handle_sync_mcp_servers)
    store.subscribe_event(
        AssistantDownloadOllamaModelEvent,
        handle_ollama_download,
    )
    store.subscribe_event(
        AssistantDownloadPiperVoiceEvent,
        handle_piper_download,
    )
    store.subscribe_event(
        AssistantDownloadKokoroEvent,
        handle_kokoro_download,
    )
    store.subscribe_event(
        AssistantDownloadVoskModelEvent,
        handle_vosk_download,
    )

    store.dispatch(AssistantUpdateProvidersAction())
    store.dispatch(AssistantSyncMcpServersAction())

    # Warm the cached Ollama downloaded-models set so `is_setup` and the
    # catalog dot indicator reflect reality without blocking the reducer
    # path on a synchronous `ollama.list()` call.
    _ollama_engine = LLM_ENGINES.get(AssistantLLMName.OLLAMA)
    if isinstance(_ollama_engine, OllamaEngine):
        create_task(_ollama_engine.refresh_downloaded_models())

    # Same idea for Piper: scan the data dir once so the catalog dot
    # indicator reflects voices the user already downloaded in previous
    # sessions.
    _piper_engine_instance = TTS_ENGINES.get(AssistantTTSName.PIPER)
    if isinstance(_piper_engine_instance, PiperEngine):
        create_task(_piper_engine_instance.refresh_downloaded_voices())

    # Same for Kokoro: warm the ``kokoro_is_downloaded`` flag so menus
    # render with correct icons immediately on cold boot.
    _kokoro_engine_instance = TTS_ENGINES.get(AssistantTTSName.KOKORO)
    if isinstance(_kokoro_engine_instance, KokoroEngine):
        create_task(_kokoro_engine_instance.refresh_downloaded_state())

    # And for Vosk: scan the data dir once so the catalog dot indicator
    # reflects STT models the user already downloaded in previous sessions.
    _vosk_engine_instance = STT_ENGINES.get(AssistantSTTName.VOSK)
    if isinstance(_vosk_engine_instance, VoskEngine):
        create_task(_vosk_engine_instance.refresh_downloaded_models())
