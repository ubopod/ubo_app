"""Service menu items."""

from __future__ import annotations

import datetime
import pathlib
from typing import TYPE_CHECKING, TypedDict

from kivy.lang.builder import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from ubo_gui.menu.types import (
    ApplicationItem,
    HeadedMenu,
    Item,
    SubMenuItem,
)
from ubo_gui.page import PageWidget

from ubo_app.colors import (
    DANGER_COLOR,
    RUNNING_COLOR,
    STOPPED_COLOR,
    WARNING_COLOR,
)
from ubo_app.store.dispatch_action import DispatchItem
from ubo_app.store.main import store
from ubo_app.store.settings.types import (
    ErrorReport,
    SettingsClearServiceErrorsAction,
    SettingsServiceSetIsEnabledAction,
    SettingsServiceSetShouldRestartAction,
    SettingsStartServiceAction,
    SettingsStopServiceAction,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.settings.types import ServiceState


class _Callbacks(TypedDict):
    heading: Callable[[], str]
    sub_heading: Callable[[], str]
    items: Callable[[], list[Item]]


def _generate_error_report_app(error: ErrorReport) -> PageWidget:
    class ErrorReportPage(PageWidget):
        text: str = StringProperty(error.message)

        def go_up(self: ErrorReportPage) -> None:
            """Scroll up the error report."""
            self.ids.scrollable_widget.y = max(
                self.ids.scrollable_widget.y - dp(100),
                self.ids.container.y
                - (self.ids.scrollable_widget.height - self.ids.container.height),
            )

        def go_down(self: ErrorReportPage) -> None:
            """Scroll down the error report."""
            self.ids.scrollable_widget.y = min(
                self.ids.scrollable_widget.y + dp(100),
                self.ids.container.y,
            )

    return ErrorReportPage


def _callbacks(service_id: str) -> _Callbacks:  # noqa: C901
    @store.autorun(
        lambda state: (
            state.settings.services[service_id].label,
            state.settings.services[service_id].is_active,
            state.settings.services[service_id].errors,
        )
        if state.settings.services is not None and service_id in state.settings.services
        else None,
    )
    def heading(data: tuple[str, bool, list] | None) -> str:
        if data is None:
            return ''
        label, is_active, errors = data
        return (
            (
                f'[color={WARNING_COLOR}]󰪥[/color] {label}'
                if errors
                else f'[color={RUNNING_COLOR}]󰪥[/color] {label}'
            )
            if is_active
            else f'[color={STOPPED_COLOR}]󰝦[/color] {label}'
        )

    @store.autorun(
        lambda state: state.settings.services[service_id].errors
        if state.settings.services is not None and service_id in state.settings.services
        else None,
    )
    def sub_heading(errors: list[ErrorReport] | None) -> str:
        if errors is None:
            return ''

        if not errors:
            return 'No errors raised in this service'

        if len(errors) == 1:
            return '1 error raised in this service'

        return f'{len(errors)} errors raised in this service'

    @store.autorun(lambda state: state.settings.services[service_id].errors)
    def error_items(errors: list[ErrorReport]) -> list[Item]:
        return [
            ApplicationItem(
                key=str(index),
                label=datetime.datetime.fromtimestamp(
                    error.timestamp,
                )
                .astimezone()
                .strftime('%Y-%m-%d %H:%M:%S'),
                icon=f'[color={DANGER_COLOR}][/color]',
                application=_generate_error_report_app(error),
            )
            for index, error in enumerate(errors)
        ]

    @store.autorun(
        lambda state: (
            state.settings.services[service_id].errors,
            state.settings.services[service_id].is_active,
            state.settings.services[service_id].is_enabled,
            state.settings.services[service_id].should_auto_restart,
        )
        if state.settings.services is not None and service_id in state.settings.services
        else None,
    )
    def items(data: tuple[list[ErrorReport], bool, bool, bool] | None) -> list[Item]:
        if data is None:
            return []

        errors, is_active, is_enabled, should_auto_restart = data

        items: list[Item] = []

        if is_active:
            items.append(
                DispatchItem(
                    key='stop',
                    label='Stop',
                    store_action=SettingsStopServiceAction(service_id=service_id),
                    icon='',
                    background_color=DANGER_COLOR,
                ),
            )
        else:
            items.append(
                DispatchItem(
                    key='start',
                    label='Start',
                    store_action=SettingsStartServiceAction(service_id=service_id),
                    icon=f'[color={RUNNING_COLOR}][/color]',
                ),
            )

        if is_enabled:
            items.append(
                DispatchItem(
                    key='enabled',
                    label='Auto Load',
                    store_action=SettingsServiceSetIsEnabledAction(
                        service_id=service_id,
                        is_enabled=False,
                    ),
                    icon='',
                ),
            )
        else:
            items.append(
                DispatchItem(
                    key='enabled',
                    label='Auto Load',
                    store_action=SettingsServiceSetIsEnabledAction(
                        service_id=service_id,
                        is_enabled=True,
                    ),
                    icon='',
                    background_color='#000000',
                ),
            )

        if should_auto_restart:
            items.append(
                DispatchItem(
                    key='auto_restart',
                    label='Auto Restart',
                    store_action=SettingsServiceSetShouldRestartAction(
                        service_id=service_id,
                        should_auto_restart=False,
                    ),
                    icon='󰜉',
                ),
            )
        else:
            items.append(
                DispatchItem(
                    key='auto_restart',
                    label='Auto Restart',
                    store_action=SettingsServiceSetShouldRestartAction(
                        service_id=service_id,
                        should_auto_restart=True,
                    ),
                    icon='󰶕',
                    background_color='#000000',
                ),
            )

        if errors:
            items.extend(
                [
                    SubMenuItem(
                        key='errors',
                        label='Errors',
                        icon=f'[color={DANGER_COLOR}][/color]',
                        sub_menu=HeadedMenu(
                            title='Errors',
                            heading='Errors',
                            sub_heading='Errors raised in this service',
                            items=error_items,
                        ),
                    ),
                    DispatchItem(
                        key='clear_errors',
                        label='Clear errors',
                        store_action=SettingsClearServiceErrorsAction(
                            service_id=service_id,
                        ),
                        icon='',
                    ),
                ],
            )

        return items

    return {
        'heading': heading,
        'sub_heading': sub_heading,
        'items': items,
    }


def service_icon(service_id: str) -> Callable[[], str]:
    """Get the icon of a service."""

    @store.autorun(
        lambda state: (
            state.settings.services[service_id].is_active,
            state.settings.services[service_id].errors,
        )
        if state.settings.services is not None and service_id in state.settings.services
        else None,
    )
    def icon(data: tuple[bool, list[ErrorReport]] | None) -> str:
        if data is None:
            return ''
        is_active, errors = data
        return (
            (
                f'[color={WARNING_COLOR}]󰪥[/color]'
                if errors
                else f'[color={RUNNING_COLOR}]󰪥[/color]'
            )
            if is_active
            else f'[color={STOPPED_COLOR}]󰝦[/color]'
        )

    return icon


@store.autorun(lambda state: state.settings.services)
def service_items(services: dict[str, ServiceState] | None) -> list[SubMenuItem]:
    """Generate the items of the services menu."""
    if services is None:
        return []

    return [
        SubMenuItem(
            key=service.id,
            label=service.label,
            icon=service_icon(service.id),
            sub_menu=HeadedMenu(title=service.label, **_callbacks(service.id)),
        )
        for service in sorted(services.values(), key=lambda x: x.label)
    ]


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('error_report.kv').resolve().as_posix(),
)
