"""Per-service menu controller for the Services settings page.

Extracted from ``dynamic_system_menus._setup_services_menu`` to eliminate
360 lines of deeply-nested closures (3 autoruns, ~15 closures).  Each
``ServiceMenuController`` instance manages the dynamic menus and action
handlers for a single service.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, ClassVar

from redux import AutorunOptions

from ubo_app import logger
from ubo_app.colors import DANGER_COLOR, RUNNING_COLOR, STOPPED_COLOR, WARNING_COLOR
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import (
    MenuItemData,
    OpenRenderAction,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.main import store

if TYPE_CHECKING:
    from ubo_app.store.settings.types import ErrorReport, ServiceState


class ServiceMenuController:
    """Manages dynamic menus and action handlers for a single service.

    Replaces the deeply-nested ``_setup_per_service_menus`` closure with
    clear, testable methods — one per concern (detail page, log level page,
    errors page).
    """

    # Track which services have already been set up (class-level)
    _setup_ids: ClassVar[set[str]] = set()

    def __init__(self, service_id: str) -> None:
        """Initialize controller for a specific service."""
        self.service_id = service_id
        self.menu_id = f'settings:service:{service_id}'
        self.log_level_menu_id = f'settings:service:{service_id}:log_level'
        self.errors_menu_id = f'settings:service:{service_id}:errors'

    @classmethod
    def setup_if_needed(cls, service_id: str) -> None:
        """Set up action handlers and autoruns for *service_id* exactly once.

        Action handlers are registered eagerly (needed when the user taps a
        menu item).  Autoruns that keep dynamic menus in sync are set up
        lazily on first call to :meth:`ensure_autoruns` — typically when the
        user navigates to the Services settings page.
        """
        if service_id in cls._setup_ids:
            return
        cls._setup_ids.add(service_id)
        controller = cls(service_id)
        controller.register_actions()
        # Store controller for lazy autorun setup
        cls._controllers[service_id] = controller

    # Controllers pending lazy autorun setup
    _controllers: ClassVar[dict[str, ServiceMenuController]] = {}

    @classmethod
    def ensure_autoruns(cls, service_id: str) -> None:
        """Set up autoruns for *service_id* if not already done.

        Called when the user actually navigates to a service's detail page,
        avoiding 3 autoruns per service at startup.
        """
        controller = cls._controllers.pop(service_id, None)
        if controller is not None:
            controller.setup_autoruns()

    @classmethod
    def _reset(cls) -> None:
        """Clear tracked service IDs and pending controllers.

        Primarily useful for testing to ensure isolation between tests.
        """
        cls._setup_ids.clear()
        cls._controllers.clear()

    # ------------------------------------------------------------------
    # Action Registration
    # ------------------------------------------------------------------

    def register_actions(self) -> None:
        """Register all action handlers for this service.

        Uses a single parameterized handler for log level changes instead
        of registering one handler per level (7 -> 1), reducing total
        registration count per service from ~17 to ~11.
        """
        from ubo_app.store.settings.types import (
            SettingsClearServiceErrorsAction,
            SettingsServiceSetIsEnabledAction,
            SettingsServiceSetLogLevelAction,
            SettingsServiceSetShouldRestartAction,
            SettingsStartServiceAction,
            SettingsStopServiceAction,
        )

        sid = self.service_id
        prefix = f'settings:service:{sid}'

        # Navigation — also triggers lazy autorun setup
        def _navigate() -> None:
            ServiceMenuController.ensure_autoruns(sid)
            store.dispatch(StackPushMenuAction(menu_key=sid))

        register_action(f'{prefix}:navigate', _navigate)
        register_action(
            f'{prefix}:navigate_log_level',
            lambda: store.dispatch(
                StackPushMenuAction(menu_key='log_level'),
            ),
        )
        register_action(
            f'{prefix}:navigate_errors',
            lambda: store.dispatch(
                StackPushMenuAction(menu_key='errors'),
            ),
        )

        # Service operations
        register_action(
            f'{prefix}:stop',
            lambda: store.dispatch(SettingsStopServiceAction(service_id=sid)),
        )
        register_action(
            f'{prefix}:start',
            lambda: store.dispatch(SettingsStartServiceAction(service_id=sid)),
        )
        register_action(
            f'{prefix}:enable',
            lambda: store.dispatch(
                SettingsServiceSetIsEnabledAction(
                    service_id=sid, is_enabled=True,
                ),
            ),
        )
        register_action(
            f'{prefix}:disable',
            lambda: store.dispatch(
                SettingsServiceSetIsEnabledAction(
                    service_id=sid, is_enabled=False,
                ),
            ),
        )
        register_action(
            f'{prefix}:enable_restart',
            lambda: store.dispatch(
                SettingsServiceSetShouldRestartAction(
                    service_id=sid, should_auto_restart=True,
                ),
            ),
        )
        register_action(
            f'{prefix}:disable_restart',
            lambda: store.dispatch(
                SettingsServiceSetShouldRestartAction(
                    service_id=sid, should_auto_restart=False,
                ),
            ),
        )
        register_action(
            f'{prefix}:clear_errors',
            lambda: store.dispatch(
                SettingsClearServiceErrorsAction(service_id=sid),
            ),
        )

        # Single parameterized handler for all log levels (instead of one
        # per level).  The action_id encodes the level as the last segment:
        #   settings:service:<sid>:log_level:<int_level>
        def _handle_log_level(action_id: str) -> None:
            level_str = action_id.rsplit(':', maxsplit=1)[-1]
            store.dispatch(
                SettingsServiceSetLogLevelAction(
                    service_id=sid,
                    log_level=int(level_str),
                ),
            )

        register_action(
            f'{prefix}:log_level:*',
            _handle_log_level,
        )

    # ------------------------------------------------------------------
    # Autoruns
    # ------------------------------------------------------------------

    def setup_autoruns(self) -> None:
        """Set up state-driven autoruns for this service's menus."""
        self._setup_detail_autorun()
        self._setup_log_level_autorun()
        self._setup_errors_autorun()

    def _setup_detail_autorun(self) -> None:
        """Autorun for the per-service detail page."""
        sid = self.service_id
        menu_id = self.menu_id

        @store.autorun(
            lambda state, _s=sid: state.settings.services.get(_s),
            options=AutorunOptions(default_value=None),
        )
        def _sync(service_state: ServiceState | None) -> None:
            if service_state is None:
                return
            self._build_detail_menu(service_state, menu_id)

    def _build_detail_menu(
        self,
        svc: ServiceState,
        menu_id: str,
    ) -> None:
        """Build and dispatch the detail page menu for this service."""
        sid = self.service_id
        prefix = f'settings:service:{sid}'
        items: list[MenuItemData] = []

        # Start / Stop
        if svc.is_active:
            items.append(MenuItemData(
                key='stop', label='Stop', icon='\uf04d',
                background_color=DANGER_COLOR,
                action_id=f'{prefix}:stop',
            ))
        else:
            items.append(MenuItemData(
                key='start', label='Start',
                icon=f'[color={RUNNING_COLOR}]\uf04b[/color]',
                action_id=f'{prefix}:start',
            ))

        # Enable / Disable
        if svc.is_enabled:
            items.append(MenuItemData(
                key='enabled', label='Auto Load', icon='\uf205',
                action_id=f'{prefix}:disable',
            ))
            items.append(MenuItemData(
                key='log_level',
                label=f'Level: {logging.getLevelName(svc.log_level)}',
                icon='\uf4ed',
                background_color=logger.COLORS_HEX[svc.log_level],
                action_id=f'{prefix}:navigate_log_level',
            ))
        else:
            items.append(MenuItemData(
                key='enabled', label='Auto Load', icon='\uf204',
                background_color='#000000',
                action_id=f'{prefix}:enable',
            ))

        # Auto Restart
        if svc.should_auto_restart:
            items.append(MenuItemData(
                key='auto_restart', label='Auto Restart', icon='󰜉',
                action_id=f'{prefix}:disable_restart',
            ))
        else:
            items.append(MenuItemData(
                key='auto_restart', label='Auto Restart', icon='󰶕',
                background_color='#000000',
                action_id=f'{prefix}:enable_restart',
            ))

        # Errors
        if svc.errors:
            items.append(MenuItemData(
                key='errors', label='Errors',
                icon=f'[color={DANGER_COLOR}]\uf06a[/color]',
                action_id=f'{prefix}:navigate_errors',
            ))
            items.append(MenuItemData(
                key='clear_errors', label='Clear errors', icon='\uf00d',
                action_id=f'{prefix}:clear_errors',
            ))

        # Heading
        if svc.is_active:
            color = WARNING_COLOR if svc.errors else RUNNING_COLOR
            heading = f'[color={color}]󰪥[/color] {svc.label}'
        else:
            heading = f'[color={STOPPED_COLOR}]󰝦[/color] {svc.label}'

        # Sub heading
        n_errors = len(svc.errors) if svc.errors else 0
        if n_errors == 0:
            sub_heading = 'No errors raised in this service'
        elif n_errors == 1:
            sub_heading = '1 error raised in this service'
        else:
            sub_heading = f'{n_errors} errors raised in this service'

        store.dispatch(UpdateDynamicMenuAction(
            menu_id=menu_id, title=svc.label,
            heading=heading, sub_heading=sub_heading,
            items=tuple(items), placeholder='',
        ))

    def _setup_log_level_autorun(self) -> None:
        """Autorun for the log-level selection page."""
        sid = self.service_id
        mid = self.log_level_menu_id

        @store.autorun(
            lambda state, _s=sid: (
                state.settings.services[_s].log_level
                if state.settings.services and _s in state.settings.services
                else None
            ),
            options=AutorunOptions(default_value=None),
        )
        def _sync(log_level: int | None) -> None:
            if log_level is None:
                return
            self._build_log_level_menu(log_level, mid)

    def _build_log_level_menu(self, current_level: int, menu_id: str) -> None:
        """Build and dispatch the log-level menu."""
        sid = self.service_id
        items: list[MenuItemData] = []
        for level in logger.COLORS_HEX:
            selected = level == current_level
            items.append(MenuItemData(
                key=logging.getLevelName(level),
                label=logging.getLevelName(level),
                icon='󰱒' if selected else '󰄱',
                color='#ffffff' if selected else logger.COLORS_HEX[level],
                background_color=(
                    logger.COLORS_HEX[level] if selected else '#000000'
                ),
                action_id=(
                    f'settings:service:{sid}:log_level:{level}'
                ),
            ))

        store.dispatch(UpdateDynamicMenuAction(
            menu_id=menu_id,
            title=f'Log Level: {logging.getLevelName(current_level)}',
            items=tuple(items), placeholder='',
        ))

    def _setup_errors_autorun(self) -> None:
        """Autorun for the errors list page."""
        sid = self.service_id
        mid = self.errors_menu_id

        @store.autorun(
            lambda state, _s=sid: (
                state.settings.services[_s].errors
                if state.settings.services and _s in state.settings.services
                else None
            ),
            options=AutorunOptions(default_value=None),
        )
        def _sync(errors: list[ErrorReport] | None) -> None:
            if errors is None:
                return
            self._build_errors_menu(errors, mid)

    def _build_errors_menu(
        self,
        errors: list[ErrorReport],
        menu_id: str,
    ) -> None:
        """Build and dispatch the errors list menu."""
        sid = self.service_id
        items: list[MenuItemData] = []
        for index, error in enumerate(errors):
            error_action_id = f'settings:service:{sid}:error:{index}'
            register_action(
                error_action_id,
                lambda _msg=error.message: store.dispatch(
                    OpenRenderAction(
                        kind='text_viewer',
                        props={'text': _msg},
                    ),
                ),
                allow_reregister=True,
            )
            items.append(MenuItemData(
                key=str(index),
                label=datetime.datetime.fromtimestamp(error.timestamp)
                    .astimezone()
                    .strftime('%Y-%m-%d %H:%M:%S'),
                icon=f'[color={DANGER_COLOR}]\uf06a[/color]',
                action_id=error_action_id,
            ))

        store.dispatch(UpdateDynamicMenuAction(
            menu_id=menu_id, title='Errors',
            heading='Errors', sub_heading='Errors raised in this service',
            items=tuple(items), placeholder='No errors',
        ))
