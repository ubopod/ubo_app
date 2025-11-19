"""Implement `init_service` for assistant service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from engines_registry import (
    IMAGE_GENERATOR_ENGINES,
    LLM_ENGINES,
    STT_ENGINES,
    TTS_ENGINES,
)
from redux import AutorunOptions
from ubo_gui.menu.types import ActionItem, HeadedMenu, Item, SubMenuItem

from ubo_app.colors import INFO_COLOR, WARNING_COLOR
from ubo_app.constants import SECRETS_PATH
from ubo_app.constants.assistant import (
    ELEVENLABS_API_KEY_SECRET_ID,
    ELEVENLABS_VOICE_ID,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
    GROK_API_KEY_SECRET_ID,
    OPENAI_API_KEY_SECRET_ID,
)
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.store.core.types import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistanceAudioFrame,
    AssistanceImageFrame,
    AssistantHandleReportEvent,
    AssistantImageGeneratorName,
    AssistantLLMName,
    AssistantSetSelectedImageGeneratorAction,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedSTTAction,
    AssistantSetSelectedTTSAction,
    AssistantSTTName,
    AssistantTTSName,
    AssistantUpdateProvidersEvent,
)
from ubo_app.store.services.audio import AudioPlayAudioSequenceAction
from ubo_app.store.ubo_actions import UboDispatchItem
from ubo_app.utils import secrets
from ubo_app.utils.gui import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    ItemParameters,
)
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Sequence


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


async def init_service() -> None:
    """Initialize the assistant service."""
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
        }

    @store.autorun(
        lambda _: secrets_modification_time(),
        options=AutorunOptions(memoization=False),
    )
    def providers(_: float) -> Sequence[Item]:
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
            secrets_modification_time(),
        ),
        options=AutorunOptions(memoization=False),
    )
    def stt_providers(
        data: tuple[AssistantSTTName, float],
    ) -> Sequence[Item]:
        """Return items for recognition engine selection."""
        selected_stt, _ = data
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
            secrets_modification_time(),
        ),
        options=AutorunOptions(memoization=False),
    )
    def llm_providers(
        data: tuple[AssistantLLMName, float],
    ) -> Sequence[Item]:
        """Return items for LLM engine selection."""
        selected_llm, _ = data
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
            secrets_modification_time(),
        ),
        options=AutorunOptions(memoization=False),
    )
    def tts_providers(
        data: tuple[AssistantTTSName, float],
    ) -> Sequence[Item]:
        """Return items for TTS engine selection."""
        selected_tts, _ = data
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
            secrets_modification_time(),
        ),
        options=AutorunOptions(memoization=False),
    )
    def image_generator_providers(
        data: tuple[AssistantImageGeneratorName, float],
    ) -> Sequence[Item]:
        """Return items for image generator engine selection."""
        selected_image_generator, _ = data
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
    )

    store.subscribe_event(AssistantHandleReportEvent, _communicate)
    store.subscribe_event(AssistantUpdateProvidersEvent, providers)
    store.subscribe_event(AssistantUpdateProvidersEvent, stt_providers)
    store.subscribe_event(AssistantUpdateProvidersEvent, llm_providers)
    store.subscribe_event(AssistantUpdateProvidersEvent, tts_providers)
    store.subscribe_event(AssistantUpdateProvidersEvent, image_generator_providers)
