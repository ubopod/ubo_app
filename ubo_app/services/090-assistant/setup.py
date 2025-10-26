"""Implement `init_service` for assistant service."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from engines_registry import (
    IMAGE_GENERATOR_ENGINES,
    LLM_ENGINES,
    STT_ENGINES,
    TTS_ENGINES,
)
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadedMenu, Item, SubMenuItem

from ubo_app.colors import DANGER_COLOR, INFO_COLOR, WARNING_COLOR
from ubo_app.constants import SECRETS_PATH
from ubo_app.constants.assistant import (
    ASSEMBLYAI_API_KEY_SECRET_ID,
    CEREBRAS_API_KEY_SECRET_ID,
    DEEPGRAM_API_KEY_SECRET_ID,
    ELEVENLABS_API_KEY_SECRET_ID,
    ELEVENLABS_VOICE_ID,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
    GROK_API_KEY_SECRET_ID,
    OPENAI_API_KEY_SECRET_ID,
    RIME_API_KEY_SECRET_ID,
)
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuGoBackAction,
    RegisterSettingAppAction,
    SettingsCategory,
)
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistanceAudioFrame,
    AssistanceImageFrame,
    AssistantAddMcpServerEvent,
    AssistantDeleteMcpServerEvent,
    AssistantHandleReportEvent,
    AssistantImageGeneratorName,
    AssistantLLMName,
    AssistantSetSelectedImageGeneratorAction,
    AssistantSetSelectedLLMAction,
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
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    ItemParameters,
)
from ubo_app.utils.input import ubo_input
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


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


def input_mcp_server() -> None:
    """Input MCP server configuration via WebUI."""

    async def act() -> None:
        import asyncio
        import contextlib

        from mcp_servers import save_mcp_server, validate_sse_url, validate_stdio_config

        from ubo_app.store.services.assistant import (
            AssistantAddMcpServerAction,
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

            # Validate configuration
            if server_type == McpServerType.STDIO:
                is_valid, error_msg, parsed_config = validate_stdio_config(config_str)
                if not is_valid or not parsed_config:
                    logger.error(
                        'Invalid stdio configuration',
                        extra={'error': error_msg},
                    )
                    return
                # Convert dict to JSON string for gRPC compatibility
                config: str = json.dumps(parsed_config)
            else:  # SSE
                is_valid, error_msg = validate_sse_url(config_str)
                if not is_valid:
                    logger.error('Invalid SSE URL', extra={'error': error_msg})
                    return
                config = config_str

            # Save to filesystem
            server_id = save_mcp_server(name, server_type, config)

            # Dispatch action to update state
            store.dispatch(
                AssistantAddMcpServerAction(
                    name=name,
                    type=server_type,
                    config=config,
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
            from ubo_app.store.core.types import OpenApplicationAction

            store.dispatch(
                OpenApplicationAction(
                    application_id='ubo:raw-image-viewer',
                    initialization_kwargs={
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
        'assistant:enabled_mcp_servers',
        lambda state: json.dumps(list(state.assistant.enabled_mcp_servers)),
    )


def _setup_autorun_and_handlers() -> tuple:  # noqa: C901
    """Set up all autorun functions and MCP event handlers.

    Returns:
        Tuple of (providers, stt_providers, llm_providers, tts_providers,
                  image_generator_providers, mcp_servers_menu,
                  handle_add_mcp_server, handle_delete_mcp_server,
                  handle_sync_mcp_servers)

    """
    # Secrets file monitor - tracks API key changes
    @store.autorun(
        lambda _: SECRETS_PATH.stat().st_mtime if SECRETS_PATH.exists() else 0,
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
            'deepgram': secrets.read_secret(DEEPGRAM_API_KEY_SECRET_ID),
            'assemblyai': secrets.read_secret(ASSEMBLYAI_API_KEY_SECRET_ID),
            'rime': secrets.read_secret(RIME_API_KEY_SECRET_ID),
        }

    @store.autorun(
        lambda state: (
            SECRETS_PATH.stat().st_mtime if SECRETS_PATH.exists() else 0,
            state.assistant.provider_setup_status,
        ),
        options=AutorunOptions(memoization=False),
    )
    def providers(_: tuple[float, dict[str, bool]]) -> Sequence[Item]:
        """Return items for recognition engine selection."""
        providers = sorted(
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
        return [
            ActionItem(
                key=provider.name,
                label=provider.label,
                action=provider.setup,
                **(
                    _get_setup_item_parameters()
                    if provider.is_setup
                    else _get_not_setup_item_parameters()
                ),
            )
            if isinstance(provider, NeedsSetupMixin)
            else Item(
                key=provider.name,
                label=provider.label,
                icon='󰱒',
            )
            for provider in providers
        ]

    @store.autorun(
        lambda state: (
            state.assistant.selected_stt,
            SECRETS_PATH.stat().st_mtime if SECRETS_PATH.exists() else 0,
            state.assistant.provider_setup_status,
        ),
        options=AutorunOptions(memoization=False),
    )
    def stt_providers(
        selected_and_data: tuple[AssistantSTTName, float, dict[str, bool]],
    ) -> Sequence[Item]:
        """Return items for recognition engine selection."""
        selected_stt, _, _ = selected_and_data
        return [
            ActionItem(
                key=engine.name,
                label=engine.instance_label,
                action=engine.setup,
                **_get_not_setup_item_parameters(
                    is_offline=not isinstance(engine, RemoteMixin),
                ),
            )
            if isinstance(engine, NeedsSetupMixin) and not engine.is_setup
            else UboDispatchItem(
                key=engine.name,
                label=engine.instance_label,
                store_action=AssistantSetSelectedSTTAction(
                    stt_name=AssistantSTTName(engine_name),
                ),
                **(
                    _get_selected_item_parameters(
                        is_offline=not isinstance(engine, RemoteMixin),
                    )
                    if selected_stt == engine_name
                    else _get_unselected_item_parameters(
                        is_offline=not isinstance(engine, RemoteMixin),
                    )
                ),
            )
            for engine_name, engine in STT_ENGINES.items()
        ]

    @store.autorun(
        lambda state: (
            state.assistant.selected_llm,
            state.assistant.selected_models,
            SECRETS_PATH.stat().st_mtime if SECRETS_PATH.exists() else 0,
            state.assistant.provider_setup_status,
        ),
        options=AutorunOptions(memoization=False),
    )
    def llm_providers(
        selected_llm_model_data: tuple[
            AssistantLLMName,
            dict[AssistantLLMName, str],
            float,
            dict[str, bool],
        ],
    ) -> Sequence[Item]:
        """Return items for LLM engine selection."""
        selected_llm, _, _, _ = selected_llm_model_data
        return [
            ActionItem(
                key=engine.name,
                label=engine.instance_label,
                action=engine.setup,
                **_get_not_setup_item_parameters(
                    is_offline=not isinstance(engine, RemoteMixin),
                ),
            )
            if isinstance(engine, NeedsSetupMixin) and not engine.is_setup
            else UboDispatchItem(
                key=engine.name,
                label=engine.instance_label,
                store_action=AssistantSetSelectedLLMAction(
                    llm_name=AssistantLLMName(engine_name),
                ),
                **(
                    _get_selected_item_parameters(
                        is_offline=not isinstance(engine, RemoteMixin),
                    )
                    if selected_llm == engine_name
                    else _get_unselected_item_parameters(
                        is_offline=not isinstance(engine, RemoteMixin),
                    )
                ),
            )
            for engine_name, engine in LLM_ENGINES.items()
        ]

    @store.autorun(
        lambda state: (
            state.assistant.selected_tts,
            SECRETS_PATH.stat().st_mtime if SECRETS_PATH.exists() else 0,
            state.assistant.provider_setup_status,
        ),
        options=AutorunOptions(memoization=False),
    )
    def tts_providers(
        selected_and_data: tuple[AssistantTTSName, float, dict[str, bool]],
    ) -> Sequence[Item]:
        """Return items for TTS engine selection."""
        selected_tts, _, _ = selected_and_data
        return [
            ActionItem(
                key=engine.name,
                label=engine.instance_label,
                action=engine.setup,
                **_get_not_setup_item_parameters(
                    is_offline=not isinstance(engine, RemoteMixin),
                ),
            )
            if isinstance(engine, NeedsSetupMixin) and not engine.is_setup
            else UboDispatchItem(
                key=engine.name if engine else tts_name,
                label=engine.instance_label if engine else tts_name.value,
                store_action=AssistantSetSelectedTTSAction(
                    tts_name=AssistantTTSName(tts_name),
                ),
                **(
                    _get_selected_item_parameters(
                        is_offline=not isinstance(engine, RemoteMixin),
                    )
                    if selected_tts == tts_name
                    else _get_unselected_item_parameters(
                        is_offline=not isinstance(engine, RemoteMixin),
                    )
                ),
            )
            for tts_name, engine in TTS_ENGINES.items()
        ]

    @store.autorun(
        lambda state: (
            state.assistant.selected_image_generator,
            SECRETS_PATH.stat().st_mtime if SECRETS_PATH.exists() else 0,
            state.assistant.provider_setup_status,
        ),
        options=AutorunOptions(memoization=False),
    )
    def image_generator_providers(
        selected_and_data: tuple[AssistantImageGeneratorName, float, dict[str, bool]],
    ) -> Sequence[Item]:
        """Return items for image generator engine selection."""
        selected_image_generator, _, _ = selected_and_data
        return [
            ActionItem(
                key=engine.name,
                label=engine.instance_label,
                action=engine.setup,
                **_get_not_setup_item_parameters(
                    is_offline=not isinstance(engine, RemoteMixin),
                ),
            )
            if isinstance(engine, NeedsSetupMixin) and not engine.is_setup
            else UboDispatchItem(
                key=engine.name if engine else img_gen_name,
                label=engine.instance_label if engine else img_gen_name.value,
                store_action=AssistantSetSelectedImageGeneratorAction(
                    image_generator_name=AssistantImageGeneratorName(img_gen_name),
                ),
                **(
                    _get_selected_item_parameters(
                        is_offline=not isinstance(engine, RemoteMixin),
                    )
                    if selected_image_generator == img_gen_name
                    else _get_unselected_item_parameters(
                        is_offline=not isinstance(engine, RemoteMixin),
                    )
                ),
            )
            for img_gen_name, engine in IMAGE_GENERATOR_ENGINES.items()
        ]

    # MCP Tools menu - main list
    @store.autorun(
        lambda state: (
            state.assistant.mcp_servers,
            state.assistant.enabled_mcp_servers,
        ),
    )
    def mcp_servers_menu(
        state_data: tuple[dict[str, McpServerMetadata], list[str]],
    ) -> Sequence[Item]:
        """Return items for MCP servers menu."""
        # Use state as source of truth (already loaded from filesystem in reducer)
        loaded_servers, enabled_servers = state_data

        logger.debug(
            'MCP servers menu autorun triggered',
            extra={
                'server_count': len(loaded_servers),
                'server_ids': list(loaded_servers.keys()),
                'enabled_count': len(enabled_servers),
            },
        )

        items: list[Item] = [
            ActionItem(
                label='Add Server',
                icon='󰌉',
                action=input_mcp_server,
            ),
        ]

        for server_id, server in loaded_servers.items():
            is_enabled = server_id in enabled_servers
            items.append(
                SubMenuItem(
                    label=server.name,
                    sub_menu=mcp_server_menu(server_id),
                    icon='󰄬' if is_enabled else '󰖭',
                    background_color=INFO_COLOR if is_enabled else WARNING_COLOR,
                ),
            )

        return items

    def mcp_server_menu(server_id: str) -> Callable[[], HeadedMenu]:
        """Generate a dynamic menu for a specific MCP server."""
        from ubo_app.store.services.assistant import (
            AssistantDeleteMcpServerAction,
            AssistantToggleMcpServerAction,
        )

        @store.autorun(
            lambda state: (
                state.assistant.mcp_servers.get(server_id),
                server_id in state.assistant.enabled_mcp_servers,
            ),
            options=AutorunOptions(default_value=None),
        )
        def menu(
            state_data: tuple[McpServerMetadata | None, bool],
        ) -> HeadedMenu:
            server, is_enabled = state_data

            if not server:
                return HeadedMenu(
                    title='MCP Server',
                    heading='Server Not Found',
                    sub_heading='',
                    items=[],
                )

            status_text = 'Enabled' if is_enabled else 'Disabled'

            return HeadedMenu(
                title=f'MCP: {server.name}',
                heading=server.name,
                sub_heading=f'Type: {server.type} • {status_text}',
                items=[
                    UboDispatchItem(
                        label='Disable' if is_enabled else 'Enable',
                        icon='󰖭' if is_enabled else '󰄬',
                        background_color=WARNING_COLOR if is_enabled else INFO_COLOR,
                        store_action=AssistantToggleMcpServerAction(
                            server_id=server_id,
                        ),
                    ),
                    UboDispatchItem(
                        label='Delete',
                        icon='󰆴',
                        background_color=DANGER_COLOR,
                        store_action=AssistantDeleteMcpServerAction(
                            server_id=server_id,
                        ),
                    ),
                ],
            )

        return menu

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
        providers,
        stt_providers,
        llm_providers,
        tts_providers,
        image_generator_providers,
        mcp_servers_menu,
        handle_add_mcp_server,
        handle_delete_mcp_server,
    )


async def init_service() -> None:
    """Initialize the assistant service."""
    _register_persistent_stores()

    (
        providers,
        stt_providers,
        llm_providers,
        tts_providers,
        image_generator_providers,
        mcp_servers_menu,
        handle_add_mcp_server,
        handle_delete_mcp_server,
    ) = _setup_autorun_and_handlers()

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=10,
            key='providers',
            menu_item=SubMenuItem(
                label='Manage',
                icon='󰶗',
                sub_menu=HeadedMenu(
                    title='󰶗Manage',
                    heading='Setup providers to be used by different '
                    'assistant features',
                    sub_heading='',
                    items=providers,
                ),
            ),
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=50,
            key='stt',
            menu_item=SubMenuItem(
                label='Speech Recognition',
                icon='',
                sub_menu=HeadedMenu(
                    title='Speech Recognition',
                    heading='Select Active Engine',
                    sub_heading=f'[color={INFO_COLOR}]󱓻[/color] Offline '
                    f'models\n[color={WARNING_COLOR}]󱓻[/color] Online '
                    'models',
                    items=stt_providers,
                ),
            ),
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=40,
            key='llm',
            menu_item=SubMenuItem(
                label='Language Model',
                icon='󰁤',
                sub_menu=HeadedMenu(
                    title='󰁤Language Model',
                    heading='Select Active Engine',
                    sub_heading=f'[color={INFO_COLOR}]󱓻[/color] Offline '
                    f'models\n[color={WARNING_COLOR}]󱓻[/color] Online '
                    'models',
                    items=llm_providers,
                ),
            ),
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=30,
            key='tts',
            menu_item=SubMenuItem(
                label='Speech Synthesis',
                icon='󰔊',
                sub_menu=HeadedMenu(
                    title='󰁤Speech Synthesis',
                    heading='Select Active Engine',
                    sub_heading=f'[color={INFO_COLOR}]󱓻[/color] Offline '
                    f'models\n[color={WARNING_COLOR}]󱓻[/color] Online '
                    'models',
                    items=tts_providers,
                ),
            ),
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=20,
            key='image_generator',
            menu_item=SubMenuItem(
                label='Image Generator',
                icon='󰹉',
                sub_menu=HeadedMenu(
                    title='󰁤Image Generator',
                    heading='Select Active Engine',
                    sub_heading=f'[color={INFO_COLOR}]󱓻[/color] Offline '
                    f'models\n[color={WARNING_COLOR}]󱓻[/color] Online '
                    'models',
                    items=image_generator_providers,
                ),
            ),
        ),
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=15,
            key='mcp_tools',
            menu_item=SubMenuItem(
                label='MCP Tools',
                icon='󰒋',
                sub_menu=HeadedMenu(
                    title='󰒋MCP Tools',
                    heading='Model Context Protocol Tools',
                    sub_heading='Add and manage MCP servers',
                    items=mcp_servers_menu,
                ),
            ),
        ),
    )

    store.subscribe_event(AssistantHandleReportEvent, _communicate)
    store.subscribe_event(AssistantAddMcpServerEvent, handle_add_mcp_server)
    store.subscribe_event(AssistantDeleteMcpServerEvent, handle_delete_mcp_server)

    store.dispatch(AssistantUpdateProvidersAction())
    store.dispatch(AssistantSyncMcpServersAction())
