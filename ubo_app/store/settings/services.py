"""Service menu items."""

from __future__ import annotations

import datetime
import logging
import pathlib
from typing import TYPE_CHECKING

from kivy.lang.builder import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from ubo_gui.menu.types import (
    ApplicationItem,
    HeadedMenu,
    HeadlessMenu,
    Item,
    SubMenuItem,
)
from ubo_gui.page import PageWidget

from ubo_app import logger
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
    SettingsServiceSetLogLevelAction,
    SettingsServiceSetShouldRestartAction,
    SettingsStartServiceAction,
    SettingsStopServiceAction,
)
from ubo_app.utils.gui import (
    SELECTED_ITEM_PARAMETERS,
    UNSELECTED_ITEM_PARAMETERS,
    ItemParameters,
)


def _get_selected_item_parameters(log_level_: int) -> ItemParameters:
    return {
        **SELECTED_ITEM_PARAMETERS,
        'background_color': logger.COLORS_HEX[log_level_],
        'color': '#ffffff',
    }


def _get_unselected_item_parameters(log_level_: int) -> ItemParameters:
    return {
        **UNSELECTED_ITEM_PARAMETERS,
        'background_color': '#000000',
        'color': logger.COLORS_HEX[log_level_],
    }


if TYPE_CHECKING:
    from ubo_app.store.settings.types import ServiceState


def _generate_error_report_app(error: ErrorReport) -> type[PageWidget]:
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


SERVICE_ITEMS: dict[str, SubMenuItem] = {}


def _create_service_item(service: ServiceState) -> SubMenuItem:  # noqa: C901
    if service.id in SERVICE_ITEMS:
        return SERVICE_ITEMS[service.id]

    @store.autorun(
        lambda state: (
            state.settings.services[service.id].label,
            state.settings.services[service.id].is_active,
            state.settings.services[service.id].errors,
        )
        if state.settings.services is not None and service.id in state.settings.services
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
        lambda state: state.settings.services[service.id].errors
        if state.settings.services is not None and service.id in state.settings.services
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

    @store.autorun(
        lambda state: state.settings.services[service.id].errors,
    )
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
        lambda state: state.settings.services[service.id].log_level,
    )
    def log_level_items(log_level: int) -> list[Item]:
        def create_log_level_item(level: int) -> Item:
            selection_parameters = (
                _get_selected_item_parameters(level)
                if level == log_level
                else _get_unselected_item_parameters(level)
            )
            return DispatchItem(
                key=logging.getLevelName(level),
                label=logging.getLevelName(level),
                store_action=SettingsServiceSetLogLevelAction(
                    service_id=service.id,
                    log_level=level,
                ),
                **selection_parameters,
            )

        return [create_log_level_item(level) for level in logger.COLORS_HEX]

    @store.autorun(
        lambda state: state.settings.services[service.id].log_level,
    )
    def log_level_title(log_level: int) -> str:
        return f'Log Level: {logging.getLevelName(log_level)}'

    @store.autorun(
        lambda state: state.settings.services[service.id]
        if state.settings.services is not None and service.id in state.settings.services
        else None,
    )
    def items(
        service_state: ServiceState | None,
    ) -> list[Item]:
        if service_state is None:
            return []
        items: list[Item] = []

        if service_state.is_active:
            items.append(
                DispatchItem(
                    key='stop',
                    label='Stop',
                    store_action=SettingsStopServiceAction(service_id=service.id),
                    icon='',
                    background_color=DANGER_COLOR,
                ),
            )
        else:
            items.append(
                DispatchItem(
                    key='start',
                    label='Start',
                    store_action=SettingsStartServiceAction(service_id=service.id),
                    icon=f'[color={RUNNING_COLOR}][/color]',
                ),
            )

        if service_state.is_enabled:
            items.extend(
                [
                    DispatchItem(
                        key='enabled',
                        label='Auto Load',
                        store_action=SettingsServiceSetIsEnabledAction(
                            service_id=service.id,
                            is_enabled=False,
                        ),
                        icon='',
                    ),
                    SubMenuItem(
                        key='log_level',
                        label=f'Level: {logging.getLevelName(service_state.log_level)}',
                        background_color=logger.COLORS_HEX[service_state.log_level],
                        icon='',
                        sub_menu=HeadlessMenu(
                            title=log_level_title,
                            items=log_level_items,
                        ),
                    ),
                ],
            )
        else:
            items.append(
                DispatchItem(
                    key='enabled',
                    label='Auto Load',
                    store_action=SettingsServiceSetIsEnabledAction(
                        service_id=service.id,
                        is_enabled=True,
                    ),
                    icon='',
                    background_color='#000000',
                ),
            )

        if service_state.should_auto_restart:
            items.append(
                DispatchItem(
                    key='auto_restart',
                    label='Auto Restart',
                    store_action=SettingsServiceSetShouldRestartAction(
                        service_id=service.id,
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
                        service_id=service.id,
                        should_auto_restart=True,
                    ),
                    icon='󰶕',
                    background_color='#000000',
                ),
            )

        if service_state.errors:
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
                            service_id=service.id,
                        ),
                        icon='',
                    ),
                ],
            )

        return items

    @store.autorun(
        lambda state: (
            state.settings.services[service.id].is_active,
            state.settings.services[service.id].errors,
        )
        if state.settings.services is not None and service.id in state.settings.services
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

    SERVICE_ITEMS[service.id] = SubMenuItem(
        key=service.id,
        label=service.label,
        icon=icon,
        sub_menu=HeadedMenu(
            title=service.label,
            heading=heading,
            sub_heading=sub_heading,
            items=items,
        ),
    )

    return SERVICE_ITEMS[service.id]


@store.autorun(lambda state: state.settings.services)
def service_items(services: dict[str, ServiceState] | None) -> list[SubMenuItem]:
    """Generate the items of the services menu."""
    if services is None:
        return []

    return [
        _create_service_item(service)
        for service in sorted(services.values(), key=lambda x: x.label)
    ]


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('error_report.kv').resolve().as_posix(),
)
