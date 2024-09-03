# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
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
from ubo_gui.page import PageWidget

from ubo_app.store.core import RegisterSettingAppAction, SettingsCategory
from ubo_app.store.main import store
from ubo_app.utils.async_ import create_task

if TYPE_CHECKING:
    from ubo_app.store.services.rpi_connect import (
        RPiConnectState,
        RPiConnectStatus,
    )


def status_based_actions(
    status: RPiConnectStatus,
) -> list[ActionItem | ApplicationItem]:
    actions = []

    if (
        status.screen_sharing_sessions is not None
        or status.remote_shell_sessions is not None
    ):

        class RPiConnectQRCodePage(PageWidget):
            url = 'https://connect.raspberrypi.com/devices'

        actions.append(
            ApplicationItem(
                label='Show URL',
                icon='󰐲',
                application=RPiConnectQRCodePage,
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
            ApplicationItem(label='Sign in', icon='󰍂', application=SignInPage),
        )
    return actions


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
