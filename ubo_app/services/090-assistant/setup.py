"""Implement `init_service` for assistant service."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

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
    ELEVENLABS_API_KEY_SECRET_ID,
    ELEVENLABS_VOICE_ID,
    GENERIC_LLM_API_KEY_SECRET_ID,
    GENERIC_LLM_BASE_URL_SECRET_ID,
    GENERIC_LLM_MODEL_SECRET_ID,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
    GROK_API_KEY_SECRET_ID,
    MISTRAL_API_KEY_SECRET_ID,
    OPENAI_API_KEY_SECRET_ID,
    OPENROUTER_API_KEY_SECRET_ID,
    QWEN_API_KEY_SECRET_ID,
    RIME_API_KEY_SECRET_ID,
)
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuGoBackAction,
    MenuItemData,
    OpenRenderAction,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
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
    AssistantHandleReportEvent,
    AssistantImageGeneratorName,
    AssistantLLMName,
    AssistantSetSelectedImageGeneratorAction,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
    AssistantSetSelectedSTTAction,
    AssistantSetSelectedTTSAction,
    AssistantSTTName,
    AssistantSyncMcpServersAction,
    AssistantTTSName,
    AssistantUpdateProvidersAction,
    McpServerMetadata,
    McpServerType,
)
from ubo_app.store.services.audio import AudioPlayAudioSequenceAction
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
        'assistant:enabled_mcp_servers',
        lambda state: json.dumps(list(state.assistant.enabled_mcp_servers)),
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
    _llm_model_open_action_ids: list[str] = []
    _llm_model_select_action_ids: list[str] = []
    _tts_action_ids: list[str] = []
    _img_gen_action_ids: list[str] = []
    _mcp_action_ids: list[str] = []
    _mcp_server_unsubscribers: dict[str, Callable] = {}

    # Secrets file monitor - tracks API key changes
    @store.autorun(
        lambda _: secrets_modification_time(),
        options=AutorunOptions(memoization=False),
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
            'generic_llm_base_url': secrets.read_secret(
                GENERIC_LLM_BASE_URL_SECRET_ID,
            ),
            'generic_llm_api_key': secrets.read_secret(GENERIC_LLM_API_KEY_SECRET_ID),
            'generic_llm_model': secrets.read_secret(GENERIC_LLM_MODEL_SECRET_ID),
            'deepgram': secrets.read_secret(DEEPGRAM_API_KEY_SECRET_ID),
            'assemblyai': secrets.read_secret(ASSEMBLYAI_API_KEY_SECRET_ID),
            'rime': secrets.read_secret(RIME_API_KEY_SECRET_ID),
        }

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

        providers_list = sorted(
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

        items: list[MenuItemData] = []
        for provider in providers_list:
            if isinstance(provider, NeedsSetupMixin):
                action_id = f'assistant:setup-provider:{provider.name}'
                _provider_action_ids.append(action_id)
                register_action(action_id, provider.setup, allow_reregister=True)
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
            state.assistant.selected_models,
        ),
    )
    def llm_providers(
        data: tuple[
            AssistantLLMName,
            dict[str, str | None],
            dict[str, bool],
            dict[AssistantLLMName, str],
        ],
    ) -> None:
        """Update dynamic menu for LLM engine selection."""
        from engine_menu_builder import build_engine_menu

        selected_models = data[3]

        for action_id in _llm_model_open_action_ids:
            unregister_action(action_id)
        _llm_model_open_action_ids.clear()

        def _llm_extra_row_factory(
            engine_name: str,
            engine: object,
        ) -> MenuItemData | None:
            """Render the 'Model: <current>' sub-item for an LLM engine."""
            curated = getattr(engine, 'CURATED_MODELS', ())
            if not curated:
                return None
            if isinstance(engine, NeedsSetupMixin) and not engine.is_setup:
                return None

            try:
                llm_name = AssistantLLMName(engine_name)
            except ValueError:
                return None

            current_model = selected_models.get(
                llm_name,
                DEFAULT_MODELS.get(llm_name, ''),
            )
            action_id = f'assistant:open-llm-model:{engine_name}'
            _llm_model_open_action_ids.append(action_id)
            register_action(
                action_id,
                lambda en=engine_name: store.dispatch(
                    StackPushMenuAction(menu_key=f'models:{en}'),
                ),
                allow_reregister=True,
            )
            return MenuItemData(
                key=f'model:{engine_name}',
                label=f'  Model: {current_model}',
                icon='󰧑',
                color=INFO_COLOR,
                action_id=action_id,
                is_short=True,
            )

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
            extra_row_factory=_llm_extra_row_factory,
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

    return (
        secrets_monitor,
        providers,
        stt_providers,
        llm_providers,
        llm_model_pickers,
        tts_providers,
        image_generator_providers,
        mcp_servers_menu,
        handle_add_mcp_server,
        handle_delete_mcp_server,
    )


def _register_assistant_path_matchers() -> None:
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

    def _assistant_path_matcher(path: tuple[str, ...]) -> str | None:
        # Paths like ('main', 'settings', 'Assistant', 'assistant:stt')
        if (
            len(path) >= 4  # noqa: PLR2004
            and path[:3] == ('main', 'settings', 'Assistant')
        ):
            menu_key = path[3]
            # MCP server detail pages must be checked BEFORE the general
            # assistant_menus lookup, otherwise 'assistant:mcp_tools' matches
            # the list menu and the detail path is never reached.
            # Path: ('main', 'settings', 'Assistant',
            #   'assistant:mcp_tools', '{server_id}')
            if len(path) >= 5 and menu_key == 'assistant:mcp_tools':  # noqa: PLR2004
                server_id = path[4]
                return f'assistant:mcp:{server_id}'
            # LLM model picker pages
            # Path: ('main', 'settings', 'Assistant', 'assistant:llm',
            #   'models:{provider}')
            if (
                len(path) >= 5  # noqa: PLR2004
                and menu_key == 'assistant:llm'
                and path[4].startswith('models:')
            ):
                provider = path[4][len('models:') :]
                return f'assistant:llm:models:{provider}'
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
        lambda s: (
            s.assistant.selected_llm,
            tuple(sorted(s.assistant.selected_models.items())),
        ),
    )
    # Model picker submenus depend on the user's per-provider selection
    for _llm_name in LLM_ENGINES:
        register_menu_content_dependency(
            f'assistant:llm:models:{_llm_name.value}',
            lambda s, ln=_llm_name: s.assistant.selected_models.get(ln, ''),
        )
    register_menu_content_dependency(
        'assistant:tts',
        lambda s: s.assistant.selected_tts,
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
        _stt_providers,
        _llm_providers,
        _llm_model_pickers,
        _tts_providers,
        _image_generator_providers,
        _mcp_servers_menu,
        handle_add_mcp_server,
        handle_delete_mcp_server,
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

    store.dispatch(AssistantUpdateProvidersAction())
    store.dispatch(AssistantSyncMcpServersAction())
