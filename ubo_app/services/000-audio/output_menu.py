"""Settings menu for choosing where playback goes.

Hardware → Audio → Speakers, listing the four outputs plus the toggle that
follows the lineout jack automatically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from constants import AUDIO_OUTPUT_MENU_ID, AUDIO_SETTINGS_MENU_ID

from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import register_path_menu_matcher
from ubo_app.store.main import store
from ubo_app.store.services.audio import (
    AudioOutput,
    AudioSelectOutputAction,
    AudioSetLineoutAutoSwitchAction,
)
from ubo_app.utils.menu_items import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_SELECT_ACTION_PREFIX = 'audio:select_output'
_TOGGLE_AUTO_SWITCH_ACTION = 'audio:toggle_lineout_auto_switch'


def _register_action_handlers() -> None:
    """Register the handlers the menu items dispatch through.

    State cannot carry callables across the gRPC boundary, so items reference
    handlers by `action_id` instead.
    """
    for output in AudioOutput:

        def _make_handler(target: AudioOutput) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(AudioSelectOutputAction(output=target))

            return _handler

        register_action(
            f'{_SELECT_ACTION_PREFIX}:{output.value}',
            _make_handler(output),
            allow_reregister=True,
        )

    @store.with_state(lambda state: state.audio.is_lineout_auto_switch_enabled)
    def _toggle_auto_switch(is_enabled: bool) -> None:  # noqa: FBT001
        store.dispatch(AudioSetLineoutAutoSwitchAction(is_enabled=not is_enabled))

    register_action(
        _TOGGLE_AUTO_SWITCH_ACTION,
        _toggle_auto_switch,
        allow_reregister=True,
    )


def _checkbox(*, is_on: bool) -> tuple[str, str | None]:
    """Return the icon and background colour that mark an item on or off."""
    parameters = SELECTED_ITEM_PARAMETERS if is_on else UNSELECTED_ITEM_PARAMETERS
    return parameters['icon'], parameters.get('background_color')


def build_audio_main_menu() -> None:
    """Build the Audio root menu."""
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=AUDIO_SETTINGS_MENU_ID,
            title='Audio',
            items=(
                MenuItemData(
                    key='speakers',
                    label='Speakers',
                    icon='󰓃',
                    action_id='menu:select:speakers',
                ),
            ),
            placeholder='',
        ),
    )


def build_output_menu(selection: tuple[AudioOutput, bool]) -> None:
    """Build the Speakers menu: the four outputs plus the auto-switch toggle."""
    selected_output, is_auto_switch_enabled = selection
    _register_action_handlers()

    def _output_item(output: AudioOutput) -> MenuItemData:
        icon, background_color = _checkbox(is_on=output == selected_output)
        return MenuItemData(
            key=output.value,
            label=output.get_label(),
            icon=icon,
            action_id=f'{_SELECT_ACTION_PREFIX}:{output.value}',
            background_color=background_color,
        )

    toggle_icon, toggle_background_color = _checkbox(is_on=is_auto_switch_enabled)
    items = (
        *(_output_item(output) for output in AudioOutput),
        MenuItemData(
            key='lineout_auto_switch',
            label='Auto-switch on jack',
            icon=toggle_icon,
            action_id=_TOGGLE_AUTO_SWITCH_ACTION,
            background_color=toggle_background_color,
        ),
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=AUDIO_OUTPUT_MENU_ID,
            title='Speakers',
            heading='Audio Output',
            sub_heading='Select where playback is routed',
            items=items,
            placeholder='',
        ),
    )


def register_output_menu() -> Callable[[], None]:
    """Register the Audio settings app and its menus.

    Returns a callable that tears down both the path matcher and the menu
    autorun, so restarting the service does not leave either behind.
    """

    def _audio_path_matcher(path: tuple[str, ...]) -> str | None:
        # Match: ('main', 'settings', <category>, 'audio:'[, 'speakers'])
        if len(path) >= 4 and path[3] == 'audio:':  # noqa: PLR2004
            if len(path) == 4:  # noqa: PLR2004
                return AUDIO_SETTINGS_MENU_ID
            if len(path) == 5 and path[4] == 'speakers':  # noqa: PLR2004
                return AUDIO_OUTPUT_MENU_ID
        return None

    unregister_matcher = register_path_menu_matcher(
        'audio:settings',
        _audio_path_matcher,
    )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.HARDWARE,
            priority=20,
            label='Audio',
            icon='󰕾',
        ),
    )

    build_audio_main_menu()

    # Rebuilt whenever the selection or the toggle changes, so the checkmarks
    # follow an automatic switch as well as a manual one.
    rebuild_on_change = store.autorun(
        lambda state: (
            state.audio.selected_output,
            state.audio.is_lineout_auto_switch_enabled,
        ),
    )(build_output_menu)

    def unregister() -> None:
        rebuild_on_change.unsubscribe()
        unregister_matcher()

    return unregister
