"""Implement `init_service` for the localization service.

Provides the Settings → Localization → Language picker. The selected
language is persisted to ``localization:language`` and influences which
Piper voices appear in the Assistant → Manage → Piper menu (and which
voices `010-speech-synthesis` will play). Future siblings (units, time
format, location) plug into the same category.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import (
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.services.localization import (
    LanguageCode,
    LocalizationSetLanguageAction,
    language_label,
)
from ubo_app.utils.menu_items import build_selection_menu
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.utils.types import Subscriptions


LANGUAGE_MENU_ID = 'localization:language'
OPEN_LANGUAGE_ACTION_ID = 'localization:open_language_picker'


def _register_language_actions() -> None:
    for code in LanguageCode:
        action_id = f'localization:set_language:{code.value}'

        def _make_handler(target: LanguageCode) -> Callable[[], None]:
            def _handler() -> None:
                store.dispatch(LocalizationSetLanguageAction(language=target))

            return _handler

        register_action(action_id, _make_handler(code), allow_reregister=True)


@store.autorun(lambda state: state.localization.language)
def _build_language_menu(selected_language: LanguageCode) -> None:
    """Rebuild the language picker whenever the selection changes."""
    _register_language_actions()

    options = tuple(
        (
            code.value,
            language_label(code),
            f'localization:set_language:{code.value}',
        )
        for code in LanguageCode
    )

    build_selection_menu(
        options=options,
        selected_key=selected_language.value,
        menu_id=LANGUAGE_MENU_ID,
        title='Language',
        heading='System Language',
        sub_heading=(
            'Pick the language used for assistant voices and other '
            'localised features.'
        ),
    )


def _open_language_picker() -> None:
    store.dispatch(StackPushMenuAction(menu_key=LANGUAGE_MENU_ID))


def init_service() -> Subscriptions:
    """Initialize the localization service."""
    register_persistent_store(
        'localization:language',
        lambda state: state.localization.language,
    )

    register_action(
        OPEN_LANGUAGE_ACTION_ID,
        _open_language_picker,
        allow_reregister=True,
    )

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.LOCALIZATION,
            priority=0,
            label='Language',
            icon='󰗊',
            action_id=OPEN_LANGUAGE_ACTION_ID,
        ),
    )

    logger.info('Localization service initialized')

    return []
