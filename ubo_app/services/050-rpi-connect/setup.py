# ruff: noqa: D100, D103
from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from commands import (
    check_is_active,
    check_status,
    install_rpi_connect,
    sign_out,
    start_service,
    stop_service,
    uninstall_rpi_connect,
)
from kivy.lang.builder import Builder
from sign_in_page import SignInPage
from ubo_gui.menu.types import ActionItem, ApplicationItem, HeadedMenu

from ubo_app.logger import logger
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store
from ubo_app.store.ubo_actions import UboApplicationItem, register_application
from ubo_app.utils.async_ import create_task
from ubo_app.utils.gui import UboPageWidget

if TYPE_CHECKING:
    from ubo_app.store.services.rpi_connect import (
        RPiConnectState,
        RPiConnectStatus,
    )

# Dynamic menu ID for dumb UI architecture
RPI_CONNECT_MENU_ID = 'rpi-connect:main'


class _RPiConnectQRCodePage(UboPageWidget): ...


register_application(
    application=_RPiConnectQRCodePage,
    application_id='rpi-connect:qrcode-page',
)
register_application(
    application=SignInPage,
    application_id='rpi-connect:signin-page',
)


def status_based_actions(
    status: RPiConnectStatus,
) -> list[ActionItem | ApplicationItem]:
    actions = []

    if (
        status.screen_sharing_sessions is not None
        or status.remote_shell_sessions is not None
    ):
        actions.append(
            UboApplicationItem(
                label='Show URL',
                icon='󰐲',
                application_id='rpi-connect:qrcode-page',
            ),
        )
    return actions


def login_actions(*, is_signed_in: bool | None) -> list[ActionItem | ApplicationItem]:
    actions = []
    if is_signed_in:
        actions.append(
            ActionItem(label='Sign out', icon='󰍃', action=sign_out),
        )
    elif is_signed_in is False:
        actions.append(
            UboApplicationItem(
                label='Sign in',
                icon='󰍂',
                application_id='rpi-connect:signin-page',
            ),
        )
    return actions


def _register_rpi_connect_action_handlers() -> None:
    """Register action handlers for RPi Connect menu items."""
    from ubo_app.store.core.action_registry import (
        get_registered_actions,
        register_action,
    )
    from ubo_app.store.core.types import OpenApplicationAction

    # Only register once
    if 'rpi-connect:start' in get_registered_actions():
        return

    def _start_service() -> None:
        start_service()

    register_action('rpi-connect:start', _start_service)
    register_action('rpi-connect:stop', stop_service)
    register_action('rpi-connect:sign-out', sign_out)
    register_action('rpi-connect:install', install_rpi_connect)
    register_action('rpi-connect:uninstall', uninstall_rpi_connect)

    def _open_signin() -> None:
        store.dispatch(
            OpenApplicationAction(application_id='rpi-connect:signin-page'),
        )

    def _open_qrcode() -> None:
        store.dispatch(
            OpenApplicationAction(application_id='rpi-connect:qrcode-page'),
        )

    register_action('rpi-connect:sign-in', _open_signin)
    register_action('rpi-connect:show-url', _open_qrcode)


@store.autorun(lambda state: state.rpi_connect)
def update_rpi_connect_dynamic_menu(state: RPiConnectState) -> None:
    """Update the dynamic menu for RPi Connect (dumb UI architecture)."""
    _register_rpi_connect_action_handlers()

    items: list[MenuItemData] = []

    if not state.is_downloading:
        if state.is_installed:
            # Show URL if sessions are active
            if state.status and (
                state.status.screen_sharing_sessions is not None
                or state.status.remote_shell_sessions is not None
            ):
                items.append(
                    MenuItemData(
                        key='rpi-connect:show-url',
                        label='Show URL',
                        icon='󰐲',
                        action_id='rpi-connect:show-url',
                    ),
                )

            # Sign in/out actions
            if state.is_signed_in:
                items.append(
                    MenuItemData(
                        key='rpi-connect:sign-out',
                        label='Sign out',
                        icon='󰍃',
                        action_id='rpi-connect:sign-out',
                    ),
                )
            elif state.is_signed_in is False:
                items.append(
                    MenuItemData(
                        key='rpi-connect:sign-in',
                        label='Sign in',
                        icon='󰍂',
                        action_id='rpi-connect:sign-in',
                    ),
                )

            # Start/Stop action
            action_id = 'rpi-connect:stop' if state.is_active else 'rpi-connect:start'
            items.append(
                MenuItemData(
                    key='rpi-connect:toggle',
                    label='Stop' if state.is_active else 'Start',
                    icon='󰓛' if state.is_active else '󰐊',
                    action_id=action_id,
                ),
            )

        # Install/Uninstall action
        if state.is_installed is not None:
            install_label = (
                'Uninstall RPi-Connect' if state.is_installed else 'Install RPi-Connect'
            )
            install_action = (
                'rpi-connect:uninstall' if state.is_installed else 'rpi-connect:install'
            )
            items.append(
                MenuItemData(
                    key='rpi-connect:install-toggle',
                    label=install_label,
                    icon='󰇚',
                    action_id=install_action,
                ),
            )

    logger.debug(
        '[RPi Connect] Updating dynamic menu: is_installed=%s, is_active=%s',
        state.is_installed,
        state.is_active,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=RPI_CONNECT_MENU_ID,
            title='RPi Connect',
            items=tuple(items),
            placeholder='',
        ),
    )


@store.autorun(lambda state: state.rpi_connect)
def actions(state: RPiConnectState) -> list[ActionItem | ApplicationItem]:
    actions = []
    if not state.is_downloading:
        if state.is_installed:
            if state.status:
                actions.extend(status_based_actions(state.status))
            actions.extend(login_actions(is_signed_in=state.is_signed_in))
            actions.append(
                ActionItem(
                    label='Stop' if state.is_active else 'Start',
                    icon='󰓛' if state.is_active else '󰐊',
                    action=stop_service if state.is_active else start_service,
                ),
            )

        if state.is_installed is not None:
            actions.append(
                ActionItem(
                    label='Uninstall RPi-Connect'
                    if state.is_installed
                    else 'Install RPi-Connect',
                    icon='󰇚',
                    action=uninstall_rpi_connect
                    if state.is_installed
                    else install_rpi_connect,
                ),
            )
    return actions


@store.autorun(lambda state: state.rpi_connect)
def status(state: RPiConnectState) -> str:
    if state.status:
        status = 'Screen sharing: '
        if state.status.screen_sharing_sessions is None:
            status += 'unavailable'
        else:
            status += f'{state.status.screen_sharing_sessions} sessions'
        status += '\nRemote shell: '
        if state.status.remote_shell_sessions is None:
            status += 'unavailable'
        else:
            status += f'{state.status.remote_shell_sessions} sessions'
    elif state.is_downloading:
        status = 'Downloading...'
    elif state.is_installed is None:
        status = 'Checking status...'
    elif not state.is_installed:
        status = 'Not installed'
    elif not state.is_active:
        status = 'Not running'
    elif not state.is_signed_in:
        status = 'Needs authentication'
    else:
        status = 'Unknown state'
    return status


ROOT_MENU = HeadedMenu(
    title='RPi Connect',
    heading='RPi Connect',
    sub_heading=status,
    items=actions,
    placeholder='',
)


def generate_rpi_connect_menu() -> HeadedMenu:
    create_task(check_status())
    return ROOT_MENU


def init_service() -> None:
    store.dispatch(
        RegisterSettingAppAction(
            menu_item=ActionItem(
                label='RPi Connect',
                icon='',
                action=generate_rpi_connect_menu,
            ),
            category=SettingsCategory.REMOTE,
        ),
    )

    create_task(check_is_active())


Builder.load_file(
    pathlib.Path(__file__)
    .parent.joinpath('rpi_connect_qrcode_page.kv')
    .resolve()
    .as_posix(),
)
