# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from __future__ import annotations

from ubo_gui.menu.types import ApplicationItem
from ubo_gui.notification import Importance, notification_manager
from ubo_gui.prompt import PromptWidget

from ubo_app.store import dispatch
from ubo_app.store.app import RegisterAppActionPayload, RegisterSettingAppAction
from ubo_app.store.status_icons import (
    IconRegistrationAction,
    IconRegistrationActionPayload,
)


class WifiPrompt(PromptWidget):
    icon = 'wifi_off'
    prompt = 'Not Connected'
    first_option_label = 'Add'
    first_option_icon = 'add'

    def first_option_callback(self: WifiPrompt) -> None:
        notification_manager.notify(
            title='WiFi added',
            content='This WiFi network has been added',
            icon='wifi',
            sender='Wifi',
        )

    second_option_label = 'Forget'
    second_option_icon = 'delete'

    def second_option_callback(self: WifiPrompt) -> None:
        notification_manager.notify(
            title='WiFi forgotten',
            content='This WiFi network is forgotten',
            importance=Importance.CRITICAL,
            sender='WiFi',
        )


def init_service() -> None:
    dispatch(
        [
            RegisterSettingAppAction(
                payload=RegisterAppActionPayload(
                    menu_item=ApplicationItem(
                        label='WiFi',
                        application=WifiPrompt,
                        icon='wifi',
                    ),
                ),
            ),
            IconRegistrationAction(
                type='STATUS_ICONS_REGISTER',
                payload=IconRegistrationActionPayload(icon='wifi', priority=-1),
            ),
        ],
    )


if __name__ == '__ubo_service__':
    init_service()

ubo_service_name = 'WiFi'
ubo_service_description = 'WiFi app for ubo-pod'
