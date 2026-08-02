"""Implement `init_service` for assistant service."""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from redux import BaseAction

    from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
    from ubo_app.store.services.localization import LanguageCode

import playback_policy
from engines_registry import (
    IMAGE_GENERATOR_ENGINES,
    LLM_ENGINES,
    STT_ENGINES,
    TTS_ENGINES,
    first_configured_engine,
    is_engine_configured,
)
from session_recorder import setup_session_recorder

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
    ELEVENLABS_VOICE_ID_PATTERN,
    GENERIC_LLM_API_KEY_SECRET_ID,
    GENERIC_LLM_BASE_URL_SECRET_ID,
    GENERIC_LLM_MODEL_SECRET_ID,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
    GROK_API_KEY_SECRET_ID,
    MISTRAL_API_KEY_SECRET_ID,
    MOONSHINE_DOWNLOAD_NOTIFICATION_ID,
    OLLAMA_RAM_LIMIT_NOTIFICATION_ID,
    OPENAI_API_KEY_SECRET_ID,
    OPENROUTER_API_KEY_SECRET_ID,
    QWEN_API_KEY_SECRET_ID,
    RIME_API_KEY_SECRET_ID,
    VENICE_API_KEY_SECRET_ID,
)
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.engines.cloud_voice_catalog import (
    FLAT_CATALOGS,
    LANGUAGE_GROUPED_CATALOGS,
    CloudVoiceEntry,
)
from ubo_app.engines.cloud_voice_catalog import language_for as cloud_language_for
from ubo_app.engines.cloud_voice_catalog import (
    visible_languages as cloud_visible_languages,
)
from ubo_app.engines.cloud_voice_catalog import voice_for as cloud_voice_for
from ubo_app.engines.elevenlabs import ElevenLabsEngine
from ubo_app.engines.generic_llm import (
    activate_provider,
    build_generic_llm_engines,
    clear_provider_secrets,
)
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
from ubo_app.engines.mistral import MistralEngine
from ubo_app.engines.moonshine import MoonshineEngine
from ubo_app.engines.moonshine_catalog import (
    DEFAULT_MOONSHINE_MODEL_ID,
    MOONSHINE_MODELS,
)
from ubo_app.engines.moonshine_catalog import model_for as moonshine_model_for
from ubo_app.engines.moonshine_catalog import model_label as moonshine_model_label
from ubo_app.engines.ollama import OllamaEngine, _ollama_status
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
from ubo_app.store.core.bindable_actions import register_bindable_action
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
    DEFAULT_VOICES,
    LIVE_PIPELINE_SOURCE_ID,
    AssistanceAudioFrame,
    AssistanceImageFrame,
    AssistantAddElevenLabsVoiceAction,
    AssistantDeleteElevenLabsVoiceAction,
    AssistantDeleteKokoroAction,
    AssistantDeleteKokoroEvent,
    AssistantDeleteMoonshineModelAction,
    AssistantDeleteOllamaModelAction,
    AssistantDeleteOllamaModelEvent,
    AssistantDeletePiperVoiceAction,
    AssistantDeletePiperVoiceEvent,
    AssistantDeleteVoskModelAction,
    AssistantDeleteVoskModelEvent,
    AssistantDownloadKokoroAction,
    AssistantDownloadKokoroEvent,
    AssistantDownloadMoonshineModelAction,
    AssistantDownloadOllamaModelAction,
    AssistantDownloadOllamaModelEvent,
    AssistantDownloadPiperVoiceAction,
    AssistantDownloadPiperVoiceEvent,
    AssistantDownloadVoskModelAction,
    AssistantDownloadVoskModelEvent,
    AssistantGenericLLMProviderRemovedEvent,
    AssistantHandleReportEvent,
    AssistantImageGeneratorName,
    AssistantLLMName,
    AssistantRunPipelineEvent,
    AssistantSetOllamaThinkingAction,
    AssistantSetSelectedImageGeneratorAction,
    AssistantSetSelectedKokoroVoiceAction,
    AssistantSetSelectedLLMAction,
    AssistantSetSelectedModelAction,
    AssistantSetSelectedMoonshineModelAction,
    AssistantSetSelectedPiperVoiceAction,
    AssistantSetSelectedSTTAction,
    AssistantSetSelectedTTSAction,
    AssistantSetSelectedVoiceAction,
    AssistantSetSelectedVoskModelAction,
    AssistantStartListeningAction,
    AssistantStopListeningAction,
    AssistantStopTalkingAction,
    AssistantSTTName,
    AssistantSynthesizeAction,
    AssistantToggleListeningAction,
    AssistantTTSName,
    AssistantUpdateProvidersAction,
    ElevenLabsVoiceEntry,
    GenericLLMProvider,
    InfraredTriggerSource,
    MistralVoiceEntry,
    UserStopReason,
    generic_llm_instance_key,
)
from ubo_app.store.services.audio import (
    AudioPlayAudioSequenceAction,
    AudioSequenceSource,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.frame_stream import register_still
from ubo_app.utils.input import ubo_input
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    ItemParameters,
    build_selection_menu,
)
from ubo_app.utils.persistent_store import register_persistent_store

# Spoken when the user picks a TTS voice, so they immediately hear it.
VOICE_PREVIEW_TEXT = 'This is a new voice.'

# A single slot: a new generated picture replaces the previous one in place
# (`push_render` is idempotent by `stream_id`).
ASSISTANT_IMAGE_STREAM_ID = 'assistant:image'


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


def _remember_playback_choice(event: AssistantRunPipelineEvent) -> None:
    """Record a session that must not play its audio on the device speaker."""
    playback_policy.remember(
        event.session_id,
        play_locally=event.play_locally,
    )


def _communicate(event: AssistantHandleReportEvent) -> None:
    """Communicate the assistance."""
    match event.data:
        case AssistanceAudioFrame(
            audio=sample,
            index=index,
            id=id,
            is_last_frame=is_last_frame,
            session_id=session_id,
        ) if not playback_policy.should_play(
            session_id,
            is_last_frame=is_last_frame,
        ):
            # The caller wants the stream, not the speaker. Frames still reach
            # whoever requested them; they just skip the audio bus.
            pass

        case AssistanceAudioFrame(
            audio=sample,
            index=index,
            id=id,
            is_last_frame=is_last_frame,
        ):
            # Dispatch on real audio OR the end-of-stream marker. The marker is an
            # ``AssistanceAudioFrame(audio=None, is_last_frame=True)`` whose
            # resulting ``sample=None`` action breaks the audio manager's play loop
            # without the 1 s empty-buffer fallback — routed through this ordered
            # report path (not a direct dispatch) so it can't overtake the chunks.
            if sample or is_last_frame:
                # Only the live pipeline drives chat-overlay reconciliation;
                # one-shot programmatic requests share the audio bus but
                # the chat reducer must ignore them — tagging the sequence
                # with an explicit ``source`` is the discriminator
                # (preferred over parsing the free-form ``id``).
                audio_source = (
                    AudioSequenceSource.ASSISTANT_LIVE
                    if event.source_id == LIVE_PIPELINE_SOURCE_ID
                    else AudioSequenceSource.OTHER
                )
                store.dispatch(
                    AudioPlayAudioSequenceAction(
                        sample=sample,
                        id=f'assistant:{event.source_id}:{id}',
                        index=index,
                        source=audio_source,
                    ),
                )

        case AssistanceImageFrame() as image:
            # The picture travels as frame-stream events, not inline in props:
            # view data is broadcast to every client, so an image in props sent
            # a multi-megabyte payload down the store stream, which on the
            # ESP32 exceeded UBO_GRPC_WEB_MAX_FRAME and knocked the satellite
            # off the air. Props carry only the geometry.
            register_still(
                ASSISTANT_IMAGE_STREAM_ID,
                image.image,
                image.width,
                image.height,
            )
            store.dispatch(
                OpenRenderAction(
                    kind='image_viewer',
                    stream_id=ASSISTANT_IMAGE_STREAM_ID,
                    props={'width': image.width, 'height': image.height},
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
        'assistant:selected_tts_voice',
        lambda state: json.dumps(state.assistant.selected_voices),
    )
    register_persistent_store(
        'assistant:elevenlabs_voices',
        lambda state: json.dumps(
            [
                {'id': voice.id, 'label': voice.label}
                for voice in state.assistant.elevenlabs_voices
            ],
        ),
    )
    register_persistent_store(
        'assistant:generic_llm_providers',
        lambda state: json.dumps(
            [
                {'provider_id': provider.provider_id, 'label': provider.label}
                for provider in state.assistant.generic_llm_providers
            ],
        ),
    )
    register_persistent_store(
        'assistant:selected_generic_llm_provider',
        lambda state: state.assistant.selected_generic_llm_provider,
    )
    register_persistent_store(
        'assistant:ollama_thinking_enabled',
        lambda state: json.dumps(state.assistant.ollama_thinking_enabled),
    )
    register_persistent_store(
        'assistant:selected_piper_voice',
        lambda state: state.assistant.selected_piper_voice,
    )
    register_persistent_store(
        'assistant:selected_kokoro_voice',
        lambda state: state.assistant.selected_kokoro_voice,
    )
    register_persistent_store(
        'assistant:selected_moonshine_model',
        lambda state: state.assistant.selected_moonshine_model,
    )
    register_persistent_store(
        'assistant:moonshine_downloaded_models',
        lambda state: json.dumps(list(state.assistant.moonshine_downloaded_models)),
    )


def _setup_autorun_and_handlers() -> tuple:  # noqa: C901, PLR0915
    """Set up all autorun functions and event handlers.

    Returns:
        Tuple of (providers, stt_providers, llm_providers, tts_providers,
                  image_generator_providers, ...)

    """
    _provider_action_ids: list[str] = []
    _stt_action_ids: list[str] = []
    _llm_action_ids: list[str] = []
    _llm_model_select_action_ids: list[str] = []
    _provider_detail_action_ids: list[str] = []
    _piper_delete_action_ids: list[str] = []
    _vosk_delete_action_ids: list[str] = []
    _ollama_delete_action_ids: list[str] = []
    _tts_action_ids: list[str] = []
    _img_gen_action_ids: list[str] = []

    # Generic "cancel/dismiss prompt" — dispatched by the Cancel button in
    # the delete-credentials confirmation prompt. Registered once for the
    # service lifetime.
    register_action(
        'assistant:provider-detail:cancel',
        lambda: store.dispatch(MenuGoBackAction()),
        allow_reregister=True,
    )

    def _register_delete_prompt(  # noqa: PLR0913
        *,
        delete_action_id: str,
        confirm_action_id: str,
        title: str,
        prompt: str,
        action: BaseAction,
        tracker: list[str],
        pop_count: int = 1,
    ) -> None:
        """Register a "delete downloaded model" item plus its confirm prompt.

        The list item (``delete_action_id``) pushes a Yes/Cancel prompt; the
        Yes button (``confirm_action_id``) dispatches *action* then pops
        ``pop_count`` frames. Pass ``pop_count=1`` to pop just the prompt and
        land back on the (rebuilt) delete list when models remain; pass
        ``pop_count=2`` to also pop the now-empty delete list and land back on
        the provider menu when this was the last deletable model.
        """
        tracker.append(delete_action_id)
        tracker.append(confirm_action_id)
        register_action(
            confirm_action_id,
            lambda a=action, n=pop_count: store.dispatch(
                a,
                *([MenuGoBackAction()] * n),
            ),
            allow_reregister=True,
        )
        register_action(
            delete_action_id,
            lambda t=title, p=prompt, c=confirm_action_id: store.dispatch(
                StackPushPromptAction(
                    title=t,
                    prompt=p,
                    icon='󰆴',
                    items=(
                        MenuItemData(
                            key='yes',
                            label='Delete',
                            icon='󰆴',
                            color=DANGER_COLOR,
                            action_id=c,
                        ),
                        MenuItemData(
                            key='cancel',
                            label='Cancel',
                            icon='󰜺',
                            action_id='assistant:provider-detail:cancel',
                        ),
                    ),
                ),
            ),
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

    def _deduped_providers(
        generic_llm_providers: tuple[GenericLLMProvider, ...] = (),
    ) -> list[AIProviderMixin]:
        """Return all engines deduplicated by class, sorted for display.

        Named generic LLM provider instances are appended outside the
        type-dedupe map — they all share ``GenericLLMEngine`` with the
        static "Add Generic LLM" adder but must each get their own row.
        """
        static_engines = {
            type(engine): engine
            for engine in {
                *STT_ENGINES.values(),
                *LLM_ENGINES.values(),
                *TTS_ENGINES.values(),
                *IMAGE_GENERATOR_ENGINES.values(),
            }
            if engine is not None
        }.values()
        instances = build_generic_llm_engines(generic_llm_providers).values()
        return sorted(
            [*static_engines, *instances],
            key=lambda p: (
                isinstance(p, RemoteMixin),
                p.label.lower(),
            ),
        )

    # Match by *type*, not identity: ``GoogleCloudEngine`` / ``OpenAIEngine``
    # have separate per-modality instances (STT/LLM/TTS), but
    # ``_deduped_providers`` collapses them to one arbitrary instance per type.
    # Identity matching would then surface only whichever modality's instance
    # happened to survive dedup, hiding the other (e.g. the LLM model picker
    # disappearing once the engine also became a TTS voice provider).
    def _llm_name_for(provider: NeedsSetupMixin) -> AssistantLLMName | None:
        return next(
            (
                name
                for name, eng in LLM_ENGINES.items()
                if type(eng) is type(provider)
            ),
            None,
        )

    def _has_model_picker(provider: NeedsSetupMixin) -> bool:
        return _llm_name_for(provider) is not None and bool(
            getattr(provider, 'CURATED_MODELS', ()),
        )

    def _tts_name_for(provider: NeedsSetupMixin) -> AssistantTTSName | None:
        return next(
            (
                name
                for name, eng in TTS_ENGINES.items()
                if type(eng) is type(provider)
            ),
            None,
        )

    def _has_voice_picker(tts_name: AssistantTTSName) -> bool:
        return (
            tts_name in LANGUAGE_GROUPED_CATALOGS
            or tts_name in FLAT_CATALOGS
            or tts_name in {AssistantTTSName.ELEVENLABS, AssistantTTSName.MISTRAL}
        )

    def _selected_cloud_voice(
        selected_voices: dict[AssistantTTSName, str],
        tts_name: AssistantTTSName,
    ) -> str:
        return selected_voices.get(tts_name) or DEFAULT_VOICES.get(tts_name, '')

    def _cloud_voice_menu_key(tts_name: AssistantTTSName) -> str:
        """Return the menu key the provider page pushes for the voice picker."""
        if tts_name in LANGUAGE_GROUPED_CATALOGS:
            return f'{tts_name.value}:languages'
        return f'{tts_name.value}:voices'

    def _cloud_voice_label(
        tts_name: AssistantTTSName,
        voice_id: str,
        available: tuple[ElevenLabsVoiceEntry | MistralVoiceEntry, ...] = (),
    ) -> str:
        """Human label for the currently selected cloud voice."""
        if not voice_id:
            return 'Default'
        entry = cloud_voice_for(
            voice_id,
            languages=LANGUAGE_GROUPED_CATALOGS.get(tts_name, ()),
            flat=FLAT_CATALOGS.get(tts_name, ()),
        )
        if entry is not None:
            return entry.label
        for fetched_voice in available:
            if fetched_voice.id == voice_id:
                return fetched_voice.label or fetched_voice.id
        return voice_id

    def _elevenlabs_engine() -> ElevenLabsEngine | None:
        engine = TTS_ENGINES.get(AssistantTTSName.ELEVENLABS)
        return engine if isinstance(engine, ElevenLabsEngine) else None

    async def _add_elevenlabs_voice() -> None:
        """Collect a voice ID (+ optional name) and add it to the picker."""
        try:
            _, result = await ubo_input(
                title='ElevenLabs Voice',
                prompt='Enter an ElevenLabs voice ID and an optional name.',
                descriptions=[
                    WebUIInputDescription(
                        fields=[
                            InputFieldDescription(
                                name='voice_id',
                                type=InputFieldType.TEXT,
                                label='Voice ID',
                                description='Enter an ElevenLabs voice ID',
                                required=True,
                                pattern=ELEVENLABS_VOICE_ID_PATTERN,
                            ),
                            InputFieldDescription(
                                name='name',
                                type=InputFieldType.TEXT,
                                label='Name (optional)',
                                description='A human-readable name, e.g. '
                                '"Deep Voice Man"',
                                required=False,
                            ),
                        ],
                    ),
                ],
            )
        except asyncio.CancelledError:
            return
        voice_id = (result.data.get('voice_id') or '').strip()
        name = (result.data.get('name') or '').strip()
        if voice_id:
            store.dispatch(
                AssistantAddElevenLabsVoiceAction(voice_id=voice_id, name=name),
            )

    def _add_elevenlabs_voice_handler() -> None:
        create_task(_add_elevenlabs_voice())

    def _refresh_elevenlabs_voices_handler() -> None:
        engine = _elevenlabs_engine()
        if engine is not None:
            create_task(engine.fetch_voices())

    def _open_elevenlabs_voices() -> None:
        """Open the ElevenLabs voice picker, refreshing the fetched list."""
        _refresh_elevenlabs_voices_handler()
        store.dispatch(StackPushMenuAction(menu_key='elevenlabs:voices'))

    def _mistral_engine() -> MistralEngine | None:
        engine = TTS_ENGINES.get(AssistantTTSName.MISTRAL)
        return engine if isinstance(engine, MistralEngine) else None

    def _refresh_mistral_voices_handler() -> None:
        engine = _mistral_engine()
        if engine is not None:
            create_task(engine.fetch_voices())

    def _open_mistral_voices() -> None:
        """Open the Mistral voice picker, refreshing the fetched list."""
        _refresh_mistral_voices_handler()
        store.dispatch(StackPushMenuAction(menu_key='mistral:voices'))

    @store.autorun(
        lambda state: (
            secrets_monitor.value,
            state.assistant.provider_setup_status,
            state.assistant.generic_llm_providers,
        ),
    )
    def providers(
        data: tuple[
            dict[str, str | None],
            dict[str, bool],
            tuple[GenericLLMProvider, ...],
        ],
    ) -> None:
        """Update dynamic menu for provider management."""
        for action_id in _provider_action_ids:
            unregister_action(action_id)
        _provider_action_ids.clear()

        items: list[MenuItemData] = []
        for provider in _deduped_providers(data[2]):
            if isinstance(
                provider,
                (OllamaEngine, PiperEngine, KokoroEngine, VoskEngine, MoonshineEngine),
            ):
                # Ollama, Piper, Kokoro, Vosk, and Moonshine share the pattern:
                # the catalog picker is both the setup path *and* the
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
            state.assistant.generic_llm_providers,
            state.assistant.piper_downloaded_voices,
            state.assistant.vosk_downloaded_models,
            state.assistant.ollama_downloaded_models,
            state.assistant.kokoro_is_downloaded,
            state.assistant.selected_voices,
            state.assistant.elevenlabs_available_voices,
            state.assistant.elevenlabs_voices,
            state.assistant.mistral_available_voices,
            state.assistant.selected_moonshine_model,
            state.assistant.moonshine_downloaded_models,
        ),
    )
    def provider_details(  # noqa: C901, PLR0912, PLR0915
        data: tuple[
            dict[str, bool],
            dict[AssistantLLMName, str],
            dict[str, str | None],
            dict[str, tuple[str, ...]],
            dict[str, bool],
            str,
            str,
            str,
            tuple[GenericLLMProvider, ...],
            tuple[str, ...],
            tuple[str, ...],
            tuple[str, ...],
            bool,
            dict[AssistantTTSName, str],
            tuple[ElevenLabsVoiceEntry, ...],
            tuple[ElevenLabsVoiceEntry, ...],
            tuple[MistralVoiceEntry, ...],
            str,
            tuple[str, ...],
        ],
    ) -> None:
        """Build per-provider detail menus reachable from Manage Providers."""
        selected_models = data[1]
        ollama_caps = data[3]
        ollama_thinking = data[4]
        selected_piper_voice = data[5] or DEFAULT_PIPER_VOICE_ID
        selected_kokoro_voice = data[6] or DEFAULT_KOKORO_VOICE_ID
        selected_vosk_model = data[7] or DEFAULT_VOSK_MODEL_ID
        piper_downloaded_voices = data[9]
        vosk_downloaded_models = data[10]
        ollama_downloaded_models = data[11]
        kokoro_is_downloaded = data[12]
        selected_voices = data[13]
        # User-added voices first so their human-readable names win over the
        # raw-id fetched entries when labelling the selected ElevenLabs voice.
        elevenlabs_voices = (*data[15], *data[14])
        mistral_available_voices = data[16]
        selected_moonshine_model = data[17] or DEFAULT_MOONSHINE_MODEL_ID
        moonshine_downloaded_models = data[18]

        for action_id in _provider_detail_action_ids:
            unregister_action(action_id)
        _provider_detail_action_ids.clear()

        for provider in _deduped_providers(data[8]):
            if not isinstance(provider, NeedsSetupMixin):
                continue
            if not provider.is_setup and not isinstance(
                provider,
                (OllamaEngine, PiperEngine, KokoroEngine, VoskEngine, MoonshineEngine),
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

                if ollama_downloaded_models:
                    delete_list_action = (
                        'assistant:provider-detail:ollama-delete-list'
                    )
                    _provider_detail_action_ids.append(delete_list_action)
                    register_action(
                        delete_list_action,
                        lambda: store.dispatch(
                            StackPushMenuAction(menu_key='ollama:delete-models'),
                        ),
                        allow_reregister=True,
                    )
                    items.append(
                        MenuItemData(
                            key='delete-models',
                            label='Delete Models',
                            icon='󰆴',
                            color=DANGER_COLOR,
                            action_id=delete_list_action,
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
                if piper_downloaded_voices:
                    delete_list_action = (
                        'assistant:provider-detail:piper-delete-list'
                    )
                    _provider_detail_action_ids.append(delete_list_action)
                    register_action(
                        delete_list_action,
                        lambda: store.dispatch(
                            StackPushMenuAction(menu_key='piper:delete-voices'),
                        ),
                        allow_reregister=True,
                    )
                    items.append(
                        MenuItemData(
                            key='delete-voices',
                            label='Delete Voices',
                            icon='󰆴',
                            color=DANGER_COLOR,
                            action_id=delete_list_action,
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
                if kokoro_is_downloaded:
                    # Kokoro ships ALL voices in one bundle, so deletion is a
                    # single all-or-nothing action — no per-voice list.
                    _register_delete_prompt(
                        delete_action_id='assistant:kokoro:delete',
                        confirm_action_id='assistant:kokoro:confirm-delete',
                        title='Delete Voices',
                        prompt='Delete the downloaded Kokoro voices bundle? '
                        'Kokoro will need to re-download before next use.',
                        action=AssistantDeleteKokoroAction(),
                        tracker=_provider_detail_action_ids,
                    )
                    items.append(
                        MenuItemData(
                            key='delete-voices',
                            label='Delete Voices',
                            icon='󰆴',
                            color=DANGER_COLOR,
                            action_id='assistant:kokoro:delete',
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
                if vosk_downloaded_models:
                    delete_list_action = (
                        'assistant:provider-detail:vosk-delete-list'
                    )
                    _provider_detail_action_ids.append(delete_list_action)
                    register_action(
                        delete_list_action,
                        lambda: store.dispatch(
                            StackPushMenuAction(menu_key='vosk:delete-models'),
                        ),
                        allow_reregister=True,
                    )
                    items.append(
                        MenuItemData(
                            key='delete-models',
                            label='Delete Models',
                            icon='󰆴',
                            color=DANGER_COLOR,
                            action_id=delete_list_action,
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

            # Moonshine exposes a flat model picker (English-only, no Language
            # drill-down). Selecting a model is the download trigger, so the
            # picker is always rendered even before anything is downloaded.
            if isinstance(provider, MoonshineEngine):
                current_model_entry = moonshine_model_for(selected_moonshine_model)
                current_label = (
                    moonshine_model_label(current_model_entry)
                    if current_model_entry is not None
                    else selected_moonshine_model
                )
                model_action = 'assistant:provider-detail:moonshine-models'
                _provider_detail_action_ids.append(model_action)
                register_action(
                    model_action,
                    lambda: store.dispatch(
                        StackPushMenuAction(menu_key='moonshine:models'),
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
                if moonshine_downloaded_models:
                    delete_list_action = (
                        'assistant:provider-detail:moonshine-delete-list'
                    )
                    _provider_detail_action_ids.append(delete_list_action)
                    register_action(
                        delete_list_action,
                        lambda: store.dispatch(
                            StackPushMenuAction(menu_key='moonshine:delete-models'),
                        ),
                        allow_reregister=True,
                    )
                    items.append(
                        MenuItemData(
                            key='delete-models',
                            label='Delete Models',
                            icon='󰆴',
                            color=DANGER_COLOR,
                            action_id=delete_list_action,
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

            # "Voice" — for cloud TTS providers with a curated/fetched voice
            # list. Local Piper/Kokoro handled their own drill-down above.
            tts_name = _tts_name_for(provider)
            if tts_name is not None and _has_voice_picker(tts_name):
                current_voice_id = _selected_cloud_voice(selected_voices, tts_name)
                current_label = _cloud_voice_label(
                    tts_name,
                    current_voice_id,
                    (*elevenlabs_voices, *mistral_available_voices),
                )
                voice_action = (
                    f'assistant:provider-detail:select-voice:{provider.name}'
                )
                _provider_detail_action_ids.append(voice_action)
                if tts_name == AssistantTTSName.ELEVENLABS:
                    register_action(
                        voice_action,
                        _open_elevenlabs_voices,
                        allow_reregister=True,
                    )
                elif tts_name == AssistantTTSName.MISTRAL:
                    register_action(
                        voice_action,
                        _open_mistral_voices,
                        allow_reregister=True,
                    )
                else:
                    voice_menu_key = _cloud_voice_menu_key(tts_name)
                    register_action(
                        voice_action,
                        lambda key=voice_menu_key: store.dispatch(
                            StackPushMenuAction(menu_key=key),
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
            state.assistant.generic_llm_providers,
            state.assistant.selected_generic_llm_provider,
        ),
    )
    def llm_providers(
        data: tuple[
            AssistantLLMName,
            dict[str, str | None],
            dict[str, bool],
            tuple[GenericLLMProvider, ...],
            str,
        ],
    ) -> None:
        """Update dynamic menu for LLM engine selection."""
        from engine_menu_builder import build_engine_menu

        selected_llm = data[0]
        generic_llm_providers = data[3]
        selected_generic_llm_provider = data[4]

        # Named generic providers each get their own row; the static GENERIC
        # entry (the "Add Generic LLM" adder) always renders last.
        engines: dict[str, object] = {
            str(name): engine
            for name, engine in LLM_ENGINES.items()
            if name is not AssistantLLMName.GENERIC
        }
        engines.update(build_generic_llm_engines(generic_llm_providers))
        engines[str(AssistantLLMName.GENERIC)] = LLM_ENGINES[
            AssistantLLMName.GENERIC
        ]

        selected_name = (
            generic_llm_instance_key(selected_generic_llm_provider)
            if selected_llm == AssistantLLMName.GENERIC
            else str(selected_llm)
        )

        generic_prefix = f'{AssistantLLMName.GENERIC}:'

        def select_action_factory(engine_name: str) -> Callable[[], None]:
            if engine_name.startswith(generic_prefix):
                provider_id = engine_name[len(generic_prefix) :]
                return lambda: activate_provider(provider_id)
            return lambda: store.dispatch(
                AssistantSetSelectedLLMAction(
                    llm_name=AssistantLLMName(engine_name),
                ),
            )

        build_engine_menu(
            engines=engines,
            selected_name=selected_name,
            menu_id='assistant:llm',
            title='Language Model',
            action_prefix='llm',
            select_action_factory=select_action_factory,
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

    # --- Cloud TTS voice pickers (Rime / Google / Venice / OpenAI) ---------
    _cloud_voice_language_action_ids: list[str] = []
    _cloud_voice_select_action_ids: list[str] = []

    def _make_cloud_voice_handler(
        tts_name: AssistantTTSName,
        voice_id: str,
        pop_count: int,
    ) -> Callable[[], None]:
        def _handler() -> None:
            store.dispatch(
                AssistantSetSelectedVoiceAction(
                    tts_name=tts_name,
                    voice_id=voice_id,
                ),
                # Audible preview in the just-selected voice. ``tts_provider``
                # is explicit so it previews this provider even when it isn't
                # the active ``selected_tts``.
                AssistantSynthesizeAction(
                    text=VOICE_PREVIEW_TEXT,
                    session_id=uuid.uuid4().hex,
                    tts_provider=tts_name,
                ),
                *([MenuGoBackAction()] * pop_count),
            )

        return _handler

    def _build_cloud_voice_list(  # noqa: PLR0913
        *,
        menu_id: str,
        tts_name: AssistantTTSName,
        voices: tuple[CloudVoiceEntry, ...],
        selected: str,
        heading: str,
        pop_count: int,
    ) -> None:
        items: list[MenuItemData] = []
        for voice in voices:
            is_selected = voice.id == selected
            action_id = (
                f'assistant:tts:select-voice:{tts_name.value}:{voice.id}'
            )
            _cloud_voice_select_action_ids.append(action_id)
            register_action(
                action_id,
                _make_cloud_voice_handler(tts_name, voice.id, pop_count),
                allow_reregister=True,
            )
            items.append(
                MenuItemData(
                    key=voice.id,
                    label=voice.label,
                    icon='󰄬' if is_selected else '󰔊',
                    background_color=INFO_COLOR if is_selected else None,
                    action_id=action_id,
                ),
            )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=menu_id,
                title='Voices',
                heading=heading,
                sub_heading='Pick a voice',
                items=tuple(items),
            ),
        )

    @store.autorun(
        lambda state: (
            state.assistant.selected_voices,
            state.localization.language,
        ),
    )
    def cloud_voice_menus(
        data: tuple[dict[AssistantTTSName, str], LanguageCode],
    ) -> None:
        """Build the cloud TTS voice pickers, adapting to the system language."""
        selected_voices, system_language = data

        for action_id in (
            *_cloud_voice_language_action_ids,
            *_cloud_voice_select_action_ids,
        ):
            unregister_action(action_id)
        _cloud_voice_language_action_ids.clear()
        _cloud_voice_select_action_ids.clear()

        # Language-grouped providers — a Language → Voice drill-down whose
        # language list follows the selected system language.
        for tts_name, languages in LANGUAGE_GROUPED_CATALOGS.items():
            selected = _selected_cloud_voice(selected_voices, tts_name)
            current_language = cloud_language_for(languages, selected)
            lang_items: list[MenuItemData] = []
            for language in cloud_visible_languages(languages, system_language):
                open_action = (
                    f'assistant:tts:{tts_name.value}:'
                    f'open-language:{language.code.value}'
                )
                _cloud_voice_language_action_ids.append(open_action)
                register_action(
                    open_action,
                    lambda name=tts_name, code=language.code: store.dispatch(
                        StackPushMenuAction(
                            menu_key=f'{name.value}:voices:{code.value}',
                        ),
                    ),
                    allow_reregister=True,
                )
                is_current = (
                    current_language is not None
                    and current_language.code == language.code
                )
                lang_items.append(
                    MenuItemData(
                        key=language.code.value,
                        label=language.label,
                        icon='󰄬' if is_current else '󰗊',
                        background_color=INFO_COLOR if is_current else None,
                        action_id=open_action,
                    ),
                )
            store.dispatch(
                UpdateDynamicMenuAction(
                    menu_id=f'assistant:tts:{tts_name.value}:languages',
                    title='Voices',
                    heading='Voices',
                    sub_heading='Pick a language',
                    items=tuple(lang_items),
                ),
            )
            for language in languages:
                _build_cloud_voice_list(
                    menu_id=(
                        f'assistant:tts:{tts_name.value}:'
                        f'voices:{language.code.value}'
                    ),
                    tts_name=tts_name,
                    voices=language.voices,
                    selected=selected,
                    heading=language.label,
                    pop_count=2,
                )

        # Flat providers (OpenAI) — a single multilingual voice list.
        for tts_name, voices in FLAT_CATALOGS.items():
            _build_cloud_voice_list(
                menu_id=f'assistant:tts:{tts_name.value}:voices',
                tts_name=tts_name,
                voices=voices,
                selected=_selected_cloud_voice(selected_voices, tts_name),
                heading='Voices',
                pop_count=1,
            )

    # --- ElevenLabs voice picker (live-fetched + user-added IDs) -----------
    _elevenlabs_voice_action_ids: list[str] = []

    @store.autorun(
        lambda state: (
            state.assistant.selected_voices,
            state.assistant.elevenlabs_voices,
            state.assistant.elevenlabs_available_voices,
            secrets_monitor.value,
        ),
    )
    def elevenlabs_voice_menu(
        data: tuple[
            dict[AssistantTTSName, str],
            tuple[ElevenLabsVoiceEntry, ...],
            tuple[ElevenLabsVoiceEntry, ...],
            object,
        ],
    ) -> None:
        """Build the ElevenLabs voice picker (no language filter)."""
        selected_voices, user_voices, available_voices, _secrets = data
        # ``_secrets`` (secrets_monitor.value) is only a refire trigger — it can
        # still be the autorun's initial sentinel on the first run, so read the
        # primary voice from the secret directly (matches how other autoruns
        # treat secrets_monitor.value: a change signal, not a data source).
        secret_voice = secrets.read_secret(ELEVENLABS_VOICE_ID) or ''
        selected = selected_voices.get(AssistantTTSName.ELEVENLABS) or secret_voice

        for action_id in _elevenlabs_voice_action_ids:
            unregister_action(action_id)
        _elevenlabs_voice_action_ids.clear()

        # Union de-duplicated by id, ordered user-added → secret → fetched.
        # A user-supplied name takes precedence over the raw id / fetched name;
        # entries with no name fall back to the id.
        labels: dict[str, str] = {}
        for voice in user_voices:
            labels[voice.id] = voice.label or voice.id
        if secret_voice:
            labels.setdefault(secret_voice, secret_voice)
        for entry in available_voices:
            labels.setdefault(entry.id, entry.label or entry.id)

        items: list[MenuItemData] = []
        for voice_id, label in labels.items():
            is_selected = voice_id == selected
            select_action = f'assistant:tts:elevenlabs:select:{voice_id}'
            _elevenlabs_voice_action_ids.append(select_action)
            register_action(
                select_action,
                lambda vid=voice_id: store.dispatch(
                    AssistantSetSelectedVoiceAction(
                        tts_name=AssistantTTSName.ELEVENLABS,
                        voice_id=vid,
                    ),
                    AssistantSynthesizeAction(
                        text=VOICE_PREVIEW_TEXT,
                        session_id=uuid.uuid4().hex,
                        tts_provider=AssistantTTSName.ELEVENLABS,
                    ),
                    MenuGoBackAction(),
                ),
                allow_reregister=True,
            )
            items.append(
                MenuItemData(
                    key=voice_id,
                    label=label,
                    icon='󰄬' if is_selected else '󰔊',
                    background_color=INFO_COLOR if is_selected else None,
                    action_id=select_action,
                ),
            )

        # "Add Voice ID" + "Refresh voices" actions.
        add_action = 'assistant:tts:elevenlabs:add-voice'
        _elevenlabs_voice_action_ids.append(add_action)
        register_action(
            add_action,
            _add_elevenlabs_voice_handler,
            allow_reregister=True,
        )
        items.append(
            MenuItemData(
                key='add-voice',
                label='Add Voice ID',
                icon='󰐕',
                action_id=add_action,
            ),
        )
        refresh_action = 'assistant:tts:elevenlabs:refresh'
        _elevenlabs_voice_action_ids.append(refresh_action)
        register_action(
            refresh_action,
            _refresh_elevenlabs_voices_handler,
            allow_reregister=True,
        )
        items.append(
            MenuItemData(
                key='refresh',
                label='Refresh Voices',
                icon='󰑐',
                action_id=refresh_action,
            ),
        )

        # Delete prompts for user-added voices only (fetched/secret stay).
        for voice in user_voices:
            display = voice.label or voice.id
            _register_delete_prompt(
                delete_action_id=f'assistant:tts:elevenlabs:delete:{voice.id}',
                confirm_action_id=(
                    f'assistant:tts:elevenlabs:confirm-delete:{voice.id}'
                ),
                title='Delete Voice',
                prompt=f'Remove voice "{display}"?',
                action=AssistantDeleteElevenLabsVoiceAction(voice_id=voice.id),
                tracker=_elevenlabs_voice_action_ids,
                pop_count=1,
            )
            items.append(
                MenuItemData(
                    key=f'delete:{voice.id}',
                    label=f'Delete {display}',
                    icon='󰆴',
                    color=DANGER_COLOR,
                    action_id=f'assistant:tts:elevenlabs:delete:{voice.id}',
                ),
            )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:tts:elevenlabs:voices',
                title='Voices',
                heading='ElevenLabs',
                sub_heading='Pick a voice',
                items=tuple(items),
            ),
        )

    # --- Mistral voice picker (live-fetched presets + account voices) ------
    _mistral_voice_action_ids: list[str] = []

    @store.autorun(
        lambda state: (
            state.assistant.selected_voices,
            state.assistant.mistral_available_voices,
        ),
    )
    def mistral_voice_menu(
        data: tuple[
            dict[AssistantTTSName, str],
            tuple[MistralVoiceEntry, ...],
        ],
    ) -> None:
        """Build the Mistral voice picker from the live-fetched voice list."""
        selected_voices, available_voices = data
        selected = selected_voices.get(AssistantTTSName.MISTRAL) or ''

        for action_id in _mistral_voice_action_ids:
            unregister_action(action_id)
        _mistral_voice_action_ids.clear()

        items: list[MenuItemData] = []
        for entry in available_voices:
            is_selected = entry.id == selected
            select_action = f'assistant:tts:mistral:select:{entry.id}'
            _mistral_voice_action_ids.append(select_action)
            register_action(
                select_action,
                lambda vid=entry.id: store.dispatch(
                    AssistantSetSelectedVoiceAction(
                        tts_name=AssistantTTSName.MISTRAL,
                        voice_id=vid,
                    ),
                    AssistantSynthesizeAction(
                        text=VOICE_PREVIEW_TEXT,
                        session_id=uuid.uuid4().hex,
                        tts_provider=AssistantTTSName.MISTRAL,
                    ),
                    MenuGoBackAction(),
                ),
                allow_reregister=True,
            )
            items.append(
                MenuItemData(
                    key=entry.id,
                    label=entry.label or entry.id,
                    icon='󰄬' if is_selected else '󰔊',
                    background_color=INFO_COLOR if is_selected else None,
                    action_id=select_action,
                ),
            )

        refresh_action = 'assistant:tts:mistral:refresh'
        _mistral_voice_action_ids.append(refresh_action)
        register_action(
            refresh_action,
            _refresh_mistral_voices_handler,
            allow_reregister=True,
        )
        items.append(
            MenuItemData(
                key='refresh',
                label='Refresh Voices',
                icon='󰑐',
                action_id=refresh_action,
            ),
        )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:tts:mistral:voices',
                title='Voices',
                heading='Mistral',
                sub_heading='Pick a voice',
                items=tuple(items),
            ),
        )

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

    _moonshine_model_action_ids: list[str] = []
    _moonshine_delete_action_ids: list[str] = []
    # ``None`` until the first autorun fire so the initial cold-start value is
    # treated as "no transition" (no redundant provider refresh on boot).
    _moonshine_prev_downloaded: list[tuple[str, ...] | None] = [None]

    @store.autorun(
        lambda state: (
            state.assistant.selected_moonshine_model,
            state.assistant.moonshine_downloaded_models,
        ),
    )
    def moonshine_models_menu(data: tuple[str, tuple[str, ...]]) -> None:
        """Build the flat Moonshine model picker (English-only, no languages)."""
        selected_model, downloaded_models = data
        selected_model = selected_model or DEFAULT_MOONSHINE_MODEL_ID
        downloaded_set = set(downloaded_models)

        for action_id in _moonshine_model_action_ids:
            unregister_action(action_id)
        _moonshine_model_action_ids.clear()

        def _make_model_handler(
            model_id: str,
            *,
            downloaded: bool,
        ) -> Callable[[], None]:
            # Select always; additionally request an explicit download when the
            # model isn't on disk yet (selection alone never downloads). Pop back
            # to the provider menu either way.
            def _handler() -> None:
                if downloaded:
                    store.dispatch(
                        AssistantSetSelectedMoonshineModelAction(model_id=model_id),
                        MenuGoBackAction(),
                    )
                else:
                    store.dispatch(
                        AssistantSetSelectedMoonshineModelAction(model_id=model_id),
                        AssistantDownloadMoonshineModelAction(model_id=model_id),
                        MenuGoBackAction(),
                    )

            return _handler

        items: list[MenuItemData] = []
        for model in MOONSHINE_MODELS:
            is_selected = model.id == selected_model
            is_downloaded = model.id in downloaded_set
            label = moonshine_model_label(model)
            if is_downloaded and not is_selected:
                label = f'{label}  •'

            action_id = f'assistant:moonshine:select-model:{model.id}'
            _moonshine_model_action_ids.append(action_id)
            register_action(
                action_id,
                _make_model_handler(model.id, downloaded=is_downloaded),
                allow_reregister=True,
            )

            items.append(
                MenuItemData(
                    key=model.id,
                    label=label,
                    icon='󰄬'
                    if is_selected
                    else ('󰇚' if not is_downloaded else '󰧑'),
                    background_color=INFO_COLOR if is_selected else None,
                    action_id=action_id,
                ),
            )

        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:moonshine:models',
                title='Moonshine',
                heading='Moonshine',
                sub_heading='Pick a model',
                items=tuple(items),
            ),
        )

    # Remembers the previous downloading flag so the notification autorun only
    # flashes "ready" on a real download→idle transition, not on the initial
    # autorun fire (which always sees the idle '' value).
    _moonshine_prev_downloading: list[str] = ['']

    @store.autorun(lambda state: state.assistant.moonshine_downloading_model)
    def moonshine_download_notification(downloading_model: str) -> None:
        """Render an indeterminate spinner while the subprocess downloads.

        Moonshine's model is fetched inside the subprocess (local model cache),
        which reports no byte progress, so this is a spinner (``progress=nan``)
        rather than a radial bar like Vosk. The subprocess sets the downloading
        flag around its model (re)build and clears it when done.
        """
        previous = _moonshine_prev_downloading[0]
        _moonshine_prev_downloading[0] = downloading_model

        if not downloading_model:
            if previous:
                # Real download just finished — flash so the spinner closes.
                store.dispatch(
                    NotificationsAddAction(
                        notification=Notification(
                            id=MOONSHINE_DOWNLOAD_NOTIFICATION_ID,
                            title='Moonshine',
                            content='Model ready',
                            display_type=NotificationDisplayType.FLASH,
                            flash_time=1,
                            color=INFO_COLOR,
                            icon='󰄬',
                            show_dismiss_action=True,
                            dismiss_on_close=True,
                        ),
                    ),
                )
            return

        entry = moonshine_model_for(downloading_model)
        label = entry.label if entry is not None else downloading_model
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id=MOONSHINE_DOWNLOAD_NOTIFICATION_ID,
                    title='Downloading',
                    content=f'Moonshine model: {label}',
                    display_type=NotificationDisplayType.STICKY,
                    color=INFO_COLOR,
                    icon='󰇚',
                    blink=False,
                    progress=math.nan,
                    show_dismiss_action=False,
                    dismiss_on_close=False,
                ),
            ),
        )

    @store.autorun(lambda state: state.assistant.moonshine_downloaded_models)
    def moonshine_refresh_providers_on_download(
        downloaded_models: tuple[str, ...],
    ) -> None:
        """Recompute provider readiness when the downloaded set changes.

        The download happens in the subprocess, so unlike Vosk nothing core-side
        refreshes ``provider_setup_status`` after it completes. The STT engine
        menu rebuilds off that status, so without this the Moonshine row stays
        "needs setup" until some unrelated provider refresh. Skip the initial
        fire (no transition) to avoid a redundant boot-time dispatch.
        """
        previous = _moonshine_prev_downloaded[0]
        _moonshine_prev_downloaded[0] = downloaded_models
        if previous is not None and previous != downloaded_models:
            store.dispatch(AssistantUpdateProvidersAction())

    @store.autorun(lambda state: state.assistant.moonshine_downloaded_models)
    def moonshine_delete_menu(downloaded_models: tuple[str, ...]) -> None:
        """List every downloaded Moonshine model the user can delete.

        Deleting the selected model flips Moonshine to "needs setup".
        """
        for action_id in _moonshine_delete_action_ids:
            unregister_action(action_id)
        _moonshine_delete_action_ids.clear()

        # Deleting the only remaining model also pops the (then-empty) delete
        # list so the user lands back on the provider menu.
        pop_count = 2 if len(downloaded_models) == 1 else 1
        items: list[MenuItemData] = []
        for model_id in downloaded_models:
            entry = moonshine_model_for(model_id)
            label = moonshine_model_label(entry) if entry is not None else model_id
            _register_delete_prompt(
                delete_action_id=f'assistant:moonshine:delete:{model_id}',
                confirm_action_id=f'assistant:moonshine:confirm-delete:{model_id}',
                title='Delete Model',
                prompt=f'Delete downloaded model "{label}"?',
                action=AssistantDeleteMoonshineModelAction(model_id=model_id),
                tracker=_moonshine_delete_action_ids,
                pop_count=pop_count,
            )
            items.append(
                MenuItemData(
                    key=model_id,
                    label=label,
                    icon='󰆴',
                    color=DANGER_COLOR,
                    action_id=f'assistant:moonshine:delete:{model_id}',
                ),
            )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:moonshine:delete-models',
                title='Delete Models',
                heading='Delete Models',
                sub_heading='Free up disk space',
                items=tuple(items),
            ),
        )

    @store.autorun(lambda state: state.assistant.piper_downloaded_voices)
    def piper_delete_menu(downloaded_voices: tuple[str, ...]) -> None:
        """List every downloaded Piper voice the user can delete to free space.

        All downloaded voices are deletable — including the selected one;
        deleting it flips Piper to "needs setup" (its ``is_setup`` checks the
        selected voice's files), which is exactly the reset the user wants.
        """
        for action_id in _piper_delete_action_ids:
            unregister_action(action_id)
        _piper_delete_action_ids.clear()

        # Deleting the only remaining voice also pops the (then-empty) delete
        # list so the user lands back on the provider menu.
        pop_count = 2 if len(downloaded_voices) == 1 else 1
        items: list[MenuItemData] = []
        for voice_id in downloaded_voices:
            entry = voice_for(voice_id)
            label = voice_label(entry) if entry is not None else voice_id
            _register_delete_prompt(
                delete_action_id=f'assistant:piper:delete:{voice_id}',
                confirm_action_id=f'assistant:piper:confirm-delete:{voice_id}',
                title='Delete Voice',
                prompt=f'Delete downloaded voice "{label}"?',
                action=AssistantDeletePiperVoiceAction(voice_id=voice_id),
                tracker=_piper_delete_action_ids,
                pop_count=pop_count,
            )
            items.append(
                MenuItemData(
                    key=voice_id,
                    label=label,
                    icon='󰆴',
                    color=DANGER_COLOR,
                    action_id=f'assistant:piper:delete:{voice_id}',
                ),
            )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:piper:delete-voices',
                title='Delete Voices',
                heading='Delete Voices',
                sub_heading='Free up disk space',
                items=tuple(items),
            ),
        )

    @store.autorun(lambda state: state.assistant.vosk_downloaded_models)
    def vosk_delete_menu(downloaded_models: tuple[str, ...]) -> None:
        """List every downloaded Vosk model the user can delete to free space.

        Deleting the selected model flips Vosk to "needs setup".
        """
        for action_id in _vosk_delete_action_ids:
            unregister_action(action_id)
        _vosk_delete_action_ids.clear()

        # Deleting the only remaining model also pops the (then-empty) delete
        # list so the user lands back on the provider menu.
        pop_count = 2 if len(downloaded_models) == 1 else 1
        items: list[MenuItemData] = []
        for model_id in downloaded_models:
            entry = vosk_model_for(model_id)
            label = vosk_model_label(entry) if entry is not None else model_id
            _register_delete_prompt(
                delete_action_id=f'assistant:vosk:delete:{model_id}',
                confirm_action_id=f'assistant:vosk:confirm-delete:{model_id}',
                title='Delete Model',
                prompt=f'Delete downloaded model "{label}"?',
                action=AssistantDeleteVoskModelAction(model_id=model_id),
                tracker=_vosk_delete_action_ids,
                pop_count=pop_count,
            )
            items.append(
                MenuItemData(
                    key=model_id,
                    label=label,
                    icon='󰆴',
                    color=DANGER_COLOR,
                    action_id=f'assistant:vosk:delete:{model_id}',
                ),
            )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:vosk:delete-models',
                title='Delete Models',
                heading='Delete Models',
                sub_heading='Free up disk space',
                items=tuple(items),
            ),
        )

    @store.autorun(lambda state: state.assistant.ollama_downloaded_models)
    def ollama_delete_menu(downloaded_models: tuple[str, ...]) -> None:
        """List every downloaded Ollama model the user can delete to free space.

        Deleting the selected model flips Ollama to "needs setup".
        """
        for action_id in _ollama_delete_action_ids:
            unregister_action(action_id)
        _ollama_delete_action_ids.clear()

        catalog_by_tag = {
            normalize_model_tag(entry.id): entry
            for category in OLLAMA_CATALOG
            for entry in category.models
        }

        # Deleting the only remaining model also pops the (then-empty) delete
        # list so the user lands back on the provider menu.
        pop_count = 2 if len(downloaded_models) == 1 else 1
        items: list[MenuItemData] = []
        for tag in downloaded_models:
            entry = catalog_by_tag.get(tag)
            label = (
                f'{entry.label}  {format_size(entry.size_bytes)}'
                if entry is not None
                else tag
            )
            _register_delete_prompt(
                delete_action_id=f'assistant:ollama:delete:{tag}',
                confirm_action_id=f'assistant:ollama:confirm-delete:{tag}',
                title='Delete Model',
                prompt=f'Delete downloaded model "{tag}"?',
                action=AssistantDeleteOllamaModelAction(model=tag),
                tracker=_ollama_delete_action_ids,
                pop_count=pop_count,
            )
            items.append(
                MenuItemData(
                    key=tag,
                    label=label,
                    icon='󰆴',
                    color=DANGER_COLOR,
                    action_id=f'assistant:ollama:delete:{tag}',
                ),
            )
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id='assistant:ollama:delete-models',
                title='Delete Models',
                heading='Delete Models',
                sub_heading='Free up disk space',
                items=tuple(items),
            ),
        )

    def _handle_piper_delete(event: AssistantDeletePiperVoiceEvent) -> None:
        """Delete a downloaded Piper voice's files."""
        engine = _piper_engine()
        if engine is not None:
            create_task(engine.delete_voice(event.voice_id))

    def _handle_vosk_delete(event: AssistantDeleteVoskModelEvent) -> None:
        """Delete a downloaded Vosk model directory."""
        engine = _vosk_engine()
        if engine is not None:
            create_task(engine.delete_model(event.model_id))

    def _handle_kokoro_delete(_: AssistantDeleteKokoroEvent) -> None:
        """Delete the Kokoro model + voices bundle."""
        engine = _kokoro_engine()
        if engine is not None:
            create_task(engine.delete_bundle())

    def _handle_ollama_delete(event: AssistantDeleteOllamaModelEvent) -> None:
        """Delete a downloaded Ollama model from the local daemon."""
        engine = LLM_ENGINES.get(AssistantLLMName.OLLAMA)
        if isinstance(engine, OllamaEngine):
            create_task(engine.delete_model(event.model))

    @store.autorun(
        lambda state: (
            state.assistant.selected_stt,
            state.assistant.selected_llm,
            state.assistant.selected_tts,
            state.assistant.provider_setup_status,
        ),
    )
    def keep_pipeline_providers_configured(
        data: tuple[
            AssistantSTTName,
            AssistantLLMName,
            AssistantTTSName,
            dict[str, bool],
        ],
    ) -> None:
        """Auto-switch a pipeline selection that has gone unconfigured.

        When a provider's credentials are deleted or its selected on-disk model
        is removed, its ``is_setup`` flips False. Rather than letting the
        screen reader / conversation silently fail on a dangling selection,
        switch that category (STT/LLM/TTS) to another configured engine,
        preferring local over cloud. Only fires when the current selection is
        genuinely broken AND a configured alternative exists, so it converges
        and never overrides a working choice. The generic-LLM selection is left
        alone (its named providers live outside ``provider_setup_status``).

        This is the ONLY autorun that auto-dispatches ``AssistantSetSelected*``:
        the ``stt_providers`` / ``llm_providers`` / ``tts_providers`` menu
        autoruns dispatch those actions only from user-click callbacks, so there
        is no competing writer to fight (which is why this can't oscillate).
        """
        selected_stt, selected_llm, selected_tts, status = data

        # Boot guard: ``provider_setup_status`` is populated asynchronously after
        # the service starts. Until then it's empty and every engine looks
        # unconfigured; ``is_engine_configured`` already treats absent keys as
        # configured, but bail out explicitly so a half-populated status during
        # startup can never switch a still-loading selection.
        if not status:
            return

        if not is_engine_configured(STT_ENGINES, selected_stt, status):
            alternative = first_configured_engine(STT_ENGINES, status)
            if alternative is not None and alternative != selected_stt:
                store.dispatch(AssistantSetSelectedSTTAction(stt_name=alternative))

        if selected_llm != AssistantLLMName.GENERIC and not is_engine_configured(
            LLM_ENGINES,
            selected_llm,
            status,
        ):
            alternative = first_configured_engine(
                LLM_ENGINES,
                status,
                skip=(AssistantLLMName.GENERIC,),
            )
            if alternative is not None and alternative != selected_llm:
                store.dispatch(AssistantSetSelectedLLMAction(llm_name=alternative))

        if not is_engine_configured(TTS_ENGINES, selected_tts, status):
            alternative = first_configured_engine(TTS_ENGINES, status)
            if alternative is not None and alternative != selected_tts:
                store.dispatch(AssistantSetSelectedTTSAction(tts_name=alternative))

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
        moonshine_models_menu,
        moonshine_download_notification,
        moonshine_refresh_providers_on_download,
        moonshine_delete_menu,
        piper_delete_menu,
        vosk_delete_menu,
        ollama_delete_menu,
        keep_pipeline_providers_configured,
        tts_providers,
        image_generator_providers,
        _handle_ollama_download,
        _handle_piper_download,
        _handle_kokoro_download,
        _handle_vosk_download,
        _handle_ollama_delete,
        _handle_piper_delete,
        _handle_kokoro_delete,
        _handle_vosk_delete,
    )


def _handle_generic_llm_provider_removed(
    event: AssistantGenericLLMProviderRemovedEvent,
) -> None:
    """Forget a removed generic LLM provider's secrets.

    Centralized here (rather than in the engine) so both the manual delete
    flow and service-driven removals (e.g. uninstalling the Hermes Docker
    composition) share one cleanup path, outside the reduce cycle.
    """
    clear_provider_secrets(event.provider_id, was_selected=event.was_selected)


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
    }

    def _match_catalog_tail(tail: str) -> str | None:  # noqa: C901, PLR0912
        """Leaf segments owned by Ollama / Piper / Kokoro / Vosk drill-downs."""
        if tail == 'ollama:categories':
            return 'assistant:ollama:categories'
        if tail.startswith('ollama:models:'):
            return f'assistant:ollama:models:{tail[len("ollama:models:") :]}'
        if tail == 'piper:languages':
            return 'assistant:piper:languages'
        if tail.startswith('piper:voices:'):
            return f'assistant:piper:voices:{tail[len("piper:voices:") :]}'
        if tail == 'piper:delete-voices':
            return 'assistant:piper:delete-voices'
        if tail == 'vosk:delete-models':
            return 'assistant:vosk:delete-models'
        if tail == 'ollama:delete-models':
            return 'assistant:ollama:delete-models'
        if tail == 'kokoro:languages':
            return 'assistant:kokoro:languages'
        if tail.startswith('kokoro:voices:'):
            return f'assistant:kokoro:voices:{tail[len("kokoro:voices:") :]}'
        if tail == 'vosk:languages':
            return 'assistant:vosk:languages'
        if tail.startswith('vosk:models:'):
            return f'assistant:vosk:models:{tail[len("vosk:models:") :]}'
        if tail == 'moonshine:models':
            return 'assistant:moonshine:models'
        if tail == 'moonshine:delete-models':
            return 'assistant:moonshine:delete-models'
        # Cloud TTS voice pickers (language-grouped Rime/Google/Venice).
        for tts_name in LANGUAGE_GROUPED_CATALOGS:
            prefix = tts_name.value
            if tail == f'{prefix}:languages':
                return f'assistant:tts:{prefix}:languages'
            if tail.startswith(f'{prefix}:voices:'):
                return (
                    f'assistant:tts:{prefix}:voices:'
                    f'{tail[len(f"{prefix}:voices:") :]}'
                )
        # Flat cloud voice pickers (OpenAI) + ElevenLabs.
        for tts_name in FLAT_CATALOGS:
            if tail == f'{tts_name.value}:voices':
                return f'assistant:tts:{tts_name.value}:voices'
        if tail == 'elevenlabs:voices':
            return 'assistant:tts:elevenlabs:voices'
        if tail == 'mistral:voices':
            return 'assistant:tts:mistral:voices'
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


def _watch_ollama_container_status() -> None:
    """Re-evaluate provider setup status when the Ollama container state changes.

    ``OllamaEngine.is_setup`` requires the container to be RUNNING, so stopping
    or removing it must refresh ``provider_setup_status`` to flip the menu back
    to the setup (run) journey. The autorun persists via the store's listener
    set (``keep_ref``), so it outlives this function.
    """

    @store.autorun(lambda state: _ollama_status(state))
    def _on_ollama_status(_status: object) -> None:
        store.dispatch(AssistantUpdateProvidersAction())


def _register_bindable_actions() -> None:
    """Expose the assistant listening actions for binding (e.g. to IR keys).

    The factory carries the originating trigger metadata via the context so
    per-source policies can dispatch on it, and uses the registered device name
    as the trigger source label.
    """
    register_bindable_action(
        'assistant:toggle',
        'Assistant: Toggle Listening',
        lambda ctx: AssistantToggleListeningAction(
            source=InfraredTriggerSource(
                protocol=ctx.protocol,
                scancode=ctx.scancode,
                label=ctx.device_name,
            ),
        ),
        allow_reregister=True,
    )
    register_bindable_action(
        'assistant:start',
        'Assistant: Start Listening',
        lambda ctx: AssistantStartListeningAction(
            source=InfraredTriggerSource(
                protocol=ctx.protocol,
                scancode=ctx.scancode,
                label=ctx.device_name,
            ),
        ),
        allow_reregister=True,
    )
    register_bindable_action(
        'assistant:stop',
        'Assistant: Stop Listening',
        lambda ctx: AssistantStopListeningAction(
            reason=UserStopReason(
                source=InfraredTriggerSource(
                    protocol=ctx.protocol,
                    scancode=ctx.scancode,
                    label=ctx.device_name,
                ),
            ),
        ),
        allow_reregister=True,
    )
    register_bindable_action(
        'assistant:stop-talking',
        'Assistant: Stop Talking',
        lambda _ctx: AssistantStopTalkingAction(),
        allow_reregister=True,
    )


async def init_service() -> None:
    """Initialize the assistant service."""
    _register_persistent_stores()
    _register_bindable_actions()

    # Register view dependencies for menu content updates
    register_menu_content_dependency(
        'assistant:stt',
        lambda s: s.assistant.selected_stt,
    )
    register_menu_content_dependency(
        'assistant:llm',
        lambda s: (
            s.assistant.selected_llm,
            s.assistant.generic_llm_providers,
            s.assistant.selected_generic_llm_provider,
        ),
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
                s.assistant.selected_vosk_model,
                # The "Delete Downloaded …" row appears/disappears as models
                # are downloaded or removed.
                tuple(s.assistant.piper_downloaded_voices),
                tuple(s.assistant.vosk_downloaded_models),
                tuple(s.assistant.ollama_downloaded_models),
                s.assistant.kokoro_is_downloaded,
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
    # Delete-downloaded-model submenus list every downloaded model, so they
    # depend only on the downloaded set (a row vanishes after deletion).
    register_menu_content_dependency(
        'assistant:ollama:delete-models',
        lambda s: tuple(s.assistant.ollama_downloaded_models),
    )
    register_menu_content_dependency(
        'assistant:piper:delete-voices',
        lambda s: tuple(s.assistant.piper_downloaded_voices),
    )
    register_menu_content_dependency(
        'assistant:vosk:delete-models',
        lambda s: tuple(s.assistant.vosk_downloaded_models),
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
        _moonshine_models_menu,
        _moonshine_download_notification,
        _moonshine_refresh_providers_on_download,
        _moonshine_delete_menu,
        _piper_delete_menu,
        _vosk_delete_menu,
        _ollama_delete_menu,
        _keep_pipeline_providers_configured,
        _tts_providers,
        _image_generator_providers,
        handle_ollama_download,
        handle_piper_download,
        handle_kokoro_download,
        handle_vosk_download,
        handle_ollama_delete,
        handle_piper_delete,
        handle_kokoro_delete,
        handle_vosk_delete,
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
    )

    # Register path matchers for assistant sub-pages
    _register_assistant_path_matchers()

    store.subscribe_event(AssistantRunPipelineEvent, _remember_playback_choice)
    setup_session_recorder()


    store.subscribe_event(AssistantHandleReportEvent, _communicate)
    store.subscribe_event(
        AssistantGenericLLMProviderRemovedEvent,
        _handle_generic_llm_provider_removed,
    )
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
    store.subscribe_event(
        AssistantDeleteOllamaModelEvent,
        handle_ollama_delete,
    )
    store.subscribe_event(
        AssistantDeletePiperVoiceEvent,
        handle_piper_delete,
    )
    store.subscribe_event(
        AssistantDeleteKokoroEvent,
        handle_kokoro_delete,
    )
    store.subscribe_event(
        AssistantDeleteVoskModelEvent,
        handle_vosk_delete,
    )

    _watch_ollama_container_status()

    store.dispatch(AssistantUpdateProvidersAction())

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
