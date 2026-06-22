"""Implement `init_service` for speech synthesis service.

The service no longer owns any TTS engine. It forwards read-text requests to the
assistant's TTS pipeline (which synthesizes and plays the audio back through the
core audio service) and exposes a single "Screen Reader" on/off toggle under
Accessibility settings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from tts_selection import first_configured_local_tts, has_any_tts_configured

from ubo_app.colors import WARNING_COLOR
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPopToRootAction,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import (
    create_settings_path_matcher,
    register_path_menu_matcher,
)
from ubo_app.store.main import store
from ubo_app.store.services.assistant import AssistantSynthesizeAction
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDispatchItem,
    NotificationDisplayType,
    NotificationsAddAction,
    NotificationsClearEvent,
    NotificationsDisplayEvent,
)
from ubo_app.store.services.speech_synthesis import (
    SpeechSynthesisReadTextAction,
    SpeechSynthesisSetIsEnabledAction,
    SpeechSynthesisSetPreferLocalAction,
    SpeechSynthesisSynthesizeTextEvent,
)
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from ubo_app.store.services.assistant import AssistantTTSName
    from ubo_app.store.services.speech_synthesis import ReadableInformation
    from ubo_app.utils.types import Subscriptions


SCREEN_READER_MENU_ID = 'speech-synthesis:screen-reader'
TOGGLE_SCREEN_READER_ACTION_ID = 'speech-synthesis:toggle-screen-reader'
TOGGLE_PREFER_LOCAL_ACTION_ID = 'speech-synthesis:toggle-prefer-local'
NO_TTS_NOTIFICATION_ID = 'speech_synthesis:no-tts'
# The assistant registers its Text-to-Speech settings under the ASSISTANT
# category with key 'tts' (see services/090-assistant/setup.py), reachable at
# path ('main', 'settings', 'Assistant', 'assistant:tts').
ASSISTANT_TTS_MENU_KEY = 'assistant:tts'

# Last `extra_information` auto-read per notification id. Repeated displays of
# the same notification (e.g. progress updates) carry the same extra info and
# must not be re-read; the entry is dropped when the notification is cleared, so
# a later re-fire of the same id reads again. Module-level container, not a
# global.
_auto_read_cache: dict[str, ReadableInformation] = {}


@store.with_state(
    lambda state: (
        state.speech_synthesis.is_prefer_local_enabled,
        state.assistant.provider_setup_status,
    ),
)
def _preferred_tts_provider(
    data: tuple[bool, dict[str, bool]],
) -> AssistantTTSName | None:
    """Resolve the TTS provider for a read, honoring the "Prefer Local" option.

    Returns ``None`` (use the assistant's default TTS) unless "Prefer Local" is
    on and a local engine is configured, in which case the highest-priority
    configured local engine (Piper, then Kokoro) is returned.
    """
    prefer_local, provider_setup_status = data
    if not prefer_local:
        return None
    return first_configured_local_tts(provider_setup_status)


def _synthesize(event: SpeechSynthesisSynthesizeTextEvent) -> None:
    """Forward text to the assistant's TTS pipeline for synthesis and playback."""
    store.dispatch(
        AssistantSynthesizeAction(
            text=event.information.text,
            session_id=uuid4().hex,
            tts_provider=_preferred_tts_provider(),
        ),
    )


@store.with_state(lambda state: state.speech_synthesis.is_screen_reader_enabled)
def _is_screen_reader_enabled(is_enabled: bool) -> bool:  # noqa: FBT001
    return is_enabled


def _auto_read_notification(event: NotificationsDisplayEvent) -> None:
    """Read a freshly displayed notification's extra information aloud.

    Gated by the Screen Reader toggle. This is the single, renderer-agnostic
    auto-read hook — the manual "extra info" item and remote read requests are
    unaffected (they dispatch ``SpeechSynthesisReadTextAction`` directly).
    """
    notification = event.notification
    extra_information = notification.extra_information
    if (
        not extra_information
        or notification.display_type is NotificationDisplayType.BACKGROUND
        or not _is_screen_reader_enabled()
    ):
        return

    notification_id = notification.id
    if notification_id is not None:
        if _auto_read_cache.get(notification_id) == extra_information:
            return
        _auto_read_cache[notification_id] = extra_information

    store.dispatch(SpeechSynthesisReadTextAction(information=extra_information))


def _forget_notification(event: NotificationsClearEvent) -> None:
    """Drop dedup state on clear so a re-fired notification reads again."""
    notification_id = event.notification.id
    if notification_id is not None:
        _auto_read_cache.pop(notification_id, None)


def _warn_no_tts_configured() -> None:
    """Notify that the screen reader has no TTS engine to speak with.

    The action deep-links to the assistant's Text-to-Speech settings by
    rebuilding the navigation path from root (pushes are relative).
    """
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=NO_TTS_NOTIFICATION_ID,
                title='Screen Reader',
                content='No speech engine is set up. Set one up in Assistant '
                'settings so the screen reader can speak.',
                importance=Importance.MEDIUM,
                icon='󰔊',
                color=WARNING_COLOR,
                display_type=NotificationDisplayType.STICKY,
                actions=[
                    NotificationDispatchItem(
                        key='set-up-tts',
                        label='Set up',
                        icon='󰒓',
                        store_action=[
                            StackPopToRootAction(),
                            # The derived path excludes the root frame but
                            # INCLUDES 'main'; the assistant matcher only
                            # resolves the TTS drill-down (Piper/Kokoro voice
                            # download) under ('main','settings','Assistant',…),
                            # so rebuild the full chain — omitting 'main' lands
                            # on the TTS menu but dead-ends every child.
                            StackPushMenuAction(menu_key='main'),
                            StackPushMenuAction(menu_key='settings'),
                            StackPushMenuAction(
                                menu_key=SettingsCategory.ASSISTANT.value,
                            ),
                            StackPushMenuAction(menu_key=ASSISTANT_TTS_MENU_KEY),
                        ],
                        dismiss_notification=True,
                    ),
                ],
            ),
        ),
    )


def _toggle_screen_reader() -> None:
    """Flip the screen-reader enabled flag, warning if no TTS is set up."""

    @store.with_state(
        lambda state: (
            state.speech_synthesis.is_screen_reader_enabled,
            state.assistant.provider_setup_status,
        ),
    )
    def _toggle(data: tuple[bool, dict[str, bool]]) -> None:
        is_enabled, provider_setup_status = data
        turning_on = not is_enabled
        store.dispatch(SpeechSynthesisSetIsEnabledAction(is_enabled=turning_on))
        if turning_on and not has_any_tts_configured(provider_setup_status):
            _warn_no_tts_configured()

    _toggle()


def _toggle_prefer_local() -> None:
    """Flip the prefer-local-TTS flag."""

    @store.with_state(lambda state: state.speech_synthesis.is_prefer_local_enabled)
    def _toggle(is_enabled: bool) -> None:  # noqa: FBT001
        store.dispatch(SpeechSynthesisSetPreferLocalAction(is_enabled=not is_enabled))

    _toggle()


@store.autorun(
    lambda state: (
        state.speech_synthesis.is_screen_reader_enabled,
        state.speech_synthesis.is_prefer_local_enabled,
        state.assistant.provider_setup_status,
    ),
)
def update_screen_reader_dynamic_menu(
    data: tuple[bool, bool, dict[str, bool]],
) -> None:
    """Render the Screen Reader toggles menu (dumb UI)."""
    is_enabled, is_prefer_local, provider_setup_status = data
    sub_heading = (
        'Read notifications aloud automatically'
        if has_any_tts_configured(provider_setup_status)
        else '󰀦 No speech engine set up in Assistant'
    )
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=SCREEN_READER_MENU_ID,
            title='󰔊Screen Reader',
            heading='Screen Reader',
            sub_heading=sub_heading,
            items=(
                MenuItemData(
                    key='screen-reader:toggle',
                    label=f'Screen Reader: {"On" if is_enabled else "Off"}',
                    icon='󰯄' if is_enabled else '󰯅',
                    action_id=TOGGLE_SCREEN_READER_ACTION_ID,
                ),
                MenuItemData(
                    key='screen-reader:prefer-local',
                    label=f'Prefer Local: {"On" if is_prefer_local else "Off"}',
                    icon='󰯄' if is_prefer_local else '󰯅',
                    action_id=TOGGLE_PREFER_LOCAL_ACTION_ID,
                ),
            ),
            placeholder='',
        ),
    )


def init_service() -> Subscriptions:
    """Initialize speech synthesis service."""
    from ubo_app.store.core.action_registry import register_action

    register_action(
        TOGGLE_SCREEN_READER_ACTION_ID,
        _toggle_screen_reader,
        allow_reregister=True,
    )
    register_action(
        TOGGLE_PREFER_LOCAL_ACTION_ID,
        _toggle_prefer_local,
        allow_reregister=True,
    )

    unregister_path_matcher = register_path_menu_matcher(
        'speech-synthesis:settings',
        create_settings_path_matcher('speech_synthesis:', SCREEN_READER_MENU_ID),
    )

    register_persistent_store(
        'speech_synthesis:is_screen_reader_enabled',
        lambda state: state.speech_synthesis.is_screen_reader_enabled,
    )
    register_persistent_store(
        'speech_synthesis:is_prefer_local_enabled',
        lambda state: state.speech_synthesis.is_prefer_local_enabled,
    )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ACCESSIBILITY,
            priority=10,
            label='Screen Reader',
            icon='󰔊',
        ),
    )

    return [
        store.subscribe_event(SpeechSynthesisSynthesizeTextEvent, _synthesize),
        store.subscribe_event(NotificationsDisplayEvent, _auto_read_notification),
        store.subscribe_event(NotificationsClearEvent, _forget_notification),
        unregister_path_matcher,
    ]
