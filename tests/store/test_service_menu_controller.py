"""Unit tests for per-service settings menu construction and actions."""

from __future__ import annotations

import importlib
import logging
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ubo_app.colors import RUNNING_COLOR, STOPPED_COLOR, WARNING_COLOR
from ubo_app.store.settings.types import (
    ErrorReport,
    ServiceState,
)

_STORE_MAIN_MODULE = 'ubo_app.store.main'
_CONTROLLER_MODULE = 'ubo_app.store.settings.service_menu_controller'
_previous_store_main = sys.modules.get(_STORE_MAIN_MODULE)
_previous_controller = sys.modules.get(_CONTROLLER_MODULE)
_fake_store_main = ModuleType(_STORE_MAIN_MODULE)
_fake_store_main.store = object()  # type: ignore[attr-defined]
sys.modules[_STORE_MAIN_MODULE] = _fake_store_main
controller_module: ModuleType | None = None
try:
    controller_module = importlib.import_module(_CONTROLLER_MODULE)
finally:
    if _previous_store_main is None:
        del sys.modules[_STORE_MAIN_MODULE]
    else:
        sys.modules[_STORE_MAIN_MODULE] = _previous_store_main
    if _previous_controller is None:
        del sys.modules[_CONTROLLER_MODULE]
        settings_package = sys.modules['ubo_app.store.settings']
        if controller_module is not None and (
            getattr(settings_package, 'service_menu_controller', None)
            is controller_module
        ):
            delattr(settings_package, 'service_menu_controller')
assert controller_module is not None
loaded_controller_module = controller_module
ServiceMenuController = loaded_controller_module.ServiceMenuController

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.core.types import (
        OpenRenderAction,
        StackPushMenuAction,
        UpdateDynamicMenuAction,
    )


class _RecordingStore:
    """Small store double that records dispatches and autorun registrations."""

    def __init__(self) -> None:
        self.actions: list[object] = []
        self.autoruns: list[tuple[Callable[..., object], Callable[..., object]]] = []

    def dispatch(self, *actions: object) -> None:
        """Record dispatched actions."""
        self.actions.extend(actions)

    def autorun(
        self,
        selector: Callable[..., object],
        **_kwargs: object,
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        """Record an autorun selector and decorated callback."""

        def _decorate(callback: Callable[..., object]) -> Callable[..., object]:
            self.autoruns.append((selector, callback))
            return callback

        return _decorate


def _capture_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_RecordingStore, dict[str, Callable[..., object]]]:
    """Replace store/action registration with isolated recording doubles."""
    recording_store = _RecordingStore()
    handlers: dict[str, Callable[..., object]] = {}

    def _register(
        action_id: str,
        handler: Callable[..., object],
        *,
        allow_reregister: bool = False,
    ) -> Callable[..., object]:
        if not allow_reregister and action_id in handlers:
            msg = f'duplicate action: {action_id}'
            raise ValueError(msg)
        handlers[action_id] = handler
        return handler

    monkeypatch.setattr(loaded_controller_module, 'store', recording_store)
    monkeypatch.setattr(loaded_controller_module, 'register_action', _register)
    return recording_store, handlers


def _service_state(
    *,
    active: bool,
    enabled: bool,
    auto_restart: bool,
    errors: list[ErrorReport] | None = None,
) -> ServiceState:
    """Build a service state with concise branch-specific inputs."""
    return ServiceState(
        id='demo',
        label='Demo Service',
        is_active=active,
        is_enabled=enabled,
        log_level=logging.INFO,
        should_auto_restart=auto_restart,
        errors=errors or [],
    )


def test_setup_is_idempotent_and_autoruns_are_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service registers actions once and installs autoruns on first use."""
    registered: list[str] = []
    autoruns: list[str] = []
    ServiceMenuController._reset()  # noqa: SLF001
    monkeypatch.setattr(
        ServiceMenuController,
        'register_actions',
        lambda self: registered.append(self.service_id),
    )
    monkeypatch.setattr(
        ServiceMenuController,
        'setup_autoruns',
        lambda self: autoruns.append(self.service_id),
    )

    ServiceMenuController.setup_if_needed('demo')
    ServiceMenuController.setup_if_needed('demo')
    ServiceMenuController.ensure_autoruns('demo')
    ServiceMenuController.ensure_autoruns('demo')

    assert registered == ['demo']
    assert autoruns == ['demo']
    ServiceMenuController._reset()  # noqa: SLF001


def test_registered_actions_dispatch_service_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every service-menu action translates to the expected store action."""
    recording_store, handlers = _capture_actions(monkeypatch)
    controller = ServiceMenuController('demo')
    prefix = 'settings:service:demo'
    controller.register_actions()

    handlers[f'{prefix}:navigate']()
    handlers[f'{prefix}:navigate_log_level']()
    handlers[f'{prefix}:navigate_errors']()
    handlers[f'{prefix}:stop']()
    handlers[f'{prefix}:start']()
    handlers[f'{prefix}:enable']()
    handlers[f'{prefix}:disable']()
    handlers[f'{prefix}:enable_restart']()
    handlers[f'{prefix}:disable_restart']()
    handlers[f'{prefix}:clear_errors']()
    handlers[f'{prefix}:log_level:*'](f'{prefix}:log_level:10')

    assert [type(action).__name__ for action in recording_store.actions] == [
        'StackPushMenuAction',
        'StackPushMenuAction',
        'StackPushMenuAction',
        'SettingsStopServiceAction',
        'SettingsStartServiceAction',
        'SettingsServiceSetIsEnabledAction',
        'SettingsServiceSetIsEnabledAction',
        'SettingsServiceSetShouldRestartAction',
        'SettingsServiceSetShouldRestartAction',
        'SettingsClearServiceErrorsAction',
        'SettingsServiceSetLogLevelAction',
    ]
    assert [
        cast('StackPushMenuAction', action).menu_key
        for action in recording_store.actions[:3]
    ] == ['demo', 'log_level', 'errors']
    assert [
        cast('SimpleNamespace', action).service_id
        for action in recording_store.actions[3:]
    ] == [
        'demo',
    ] * 8
    assert [
        cast('SimpleNamespace', action).is_enabled
        for action in recording_store.actions[5:7]
    ] == [
        True,
        False,
    ]
    assert [
        cast('SimpleNamespace', action).should_auto_restart
        for action in recording_store.actions[7:9]
    ] == [True, False]
    assert (
        cast('SimpleNamespace', recording_store.actions[-1]).log_level == logging.DEBUG
    )


@pytest.mark.parametrize(
    ('service', 'expected_keys', 'heading_color', 'sub_heading'),
    [
        pytest.param(
            _service_state(active=False, enabled=False, auto_restart=False),
            ['start', 'enabled', 'auto_restart'],
            STOPPED_COLOR,
            'No errors raised in this service',
            id='inactive-disabled-no-errors',
        ),
        pytest.param(
            _service_state(
                active=True,
                enabled=True,
                auto_restart=True,
                errors=[ErrorReport(timestamp=1, message='one')],
            ),
            ['stop', 'enabled', 'log_level', 'auto_restart', 'errors', 'clear_errors'],
            WARNING_COLOR,
            '1 error raised in this service',
            id='active-enabled-one-error',
        ),
        pytest.param(
            _service_state(
                active=True,
                enabled=True,
                auto_restart=False,
                errors=[
                    ErrorReport(timestamp=1, message='one'),
                    ErrorReport(timestamp=2, message='two'),
                ],
            ),
            ['stop', 'enabled', 'log_level', 'auto_restart', 'errors', 'clear_errors'],
            WARNING_COLOR,
            '2 errors raised in this service',
            id='active-enabled-multiple-errors',
        ),
        pytest.param(
            _service_state(active=True, enabled=False, auto_restart=False),
            ['stop', 'enabled', 'auto_restart'],
            RUNNING_COLOR,
            'No errors raised in this service',
            id='active-disabled-no-errors',
        ),
    ],
)
def test_detail_menu_covers_service_state_branches(
    monkeypatch: pytest.MonkeyPatch,
    service: ServiceState,
    expected_keys: list[str],
    heading_color: str,
    sub_heading: str,
) -> None:
    """Detail menus reflect lifecycle, enablement, restart, and error state."""
    recording_store, _ = _capture_actions(monkeypatch)
    controller = ServiceMenuController('demo')

    controller._build_detail_menu(service, controller.menu_id)  # noqa: SLF001

    action = cast('UpdateDynamicMenuAction', recording_store.actions[-1])
    assert action.menu_id == 'settings:service:demo'
    assert action.title == 'Demo Service'
    assert [item.key for item in action.items if item is not None] == expected_keys
    assert f'[color={heading_color}]' in cast('str', action.heading)
    assert action.sub_heading == sub_heading


def test_log_level_menu_marks_current_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exactly one log level is selected and all choices have action IDs."""
    recording_store, _ = _capture_actions(monkeypatch)
    controller = ServiceMenuController('demo')

    controller._build_log_level_menu(logging.WARNING, controller.log_level_menu_id)  # noqa: SLF001

    action = cast('UpdateDynamicMenuAction', recording_store.actions[-1])
    selected = [item for item in action.items if item is not None and item.icon == '󰱒']
    assert action.title == 'Log Level: WARNING'
    assert len(selected) == 1
    assert selected[0].key == 'WARNING'
    assert all(
        item is not None
        and item.action_id == f'settings:service:demo:log_level:{level}'
        for item, level in zip(
            action.items,
            loaded_controller_module.logger.COLORS_HEX,
            strict=True,
        )
    )


def test_error_menu_actions_open_the_matching_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each error row retains its own message when its handler is executed."""
    recording_store, handlers = _capture_actions(monkeypatch)
    controller = ServiceMenuController('demo')
    errors = [
        ErrorReport(timestamp=1, message='first failure'),
        ErrorReport(timestamp=2, message='second failure'),
    ]

    controller._build_errors_menu(errors, controller.errors_menu_id)  # noqa: SLF001
    handlers['settings:service:demo:error:0']()
    handlers['settings:service:demo:error:1']()

    menu_action = cast('UpdateDynamicMenuAction', recording_store.actions[0])
    opened = [
        cast('OpenRenderAction', action).props['text']
        for action in recording_store.actions[1:]
    ]
    assert [item.action_id for item in menu_action.items if item is not None] == [
        'settings:service:demo:error:0',
        'settings:service:demo:error:1',
    ]
    assert opened == ['first failure', 'second failure']


def test_setup_autoruns_syncs_each_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lazy autoruns ignore absent state and sync all three service menus."""
    recording_store, _ = _capture_actions(monkeypatch)
    controller = ServiceMenuController('demo')
    service = _service_state(active=True, enabled=True, auto_restart=True)

    controller.setup_autoruns()

    assert len(recording_store.autoruns) == 3
    detail_selector, detail_sync = recording_store.autoruns[0]
    log_selector, log_sync = recording_store.autoruns[1]
    errors_selector, errors_sync = recording_store.autoruns[2]
    state = SimpleNamespace(settings=SimpleNamespace(services={'demo': service}))
    empty_state = SimpleNamespace(settings=SimpleNamespace(services={}))
    assert detail_selector(state) == service
    assert log_selector(state) == logging.INFO
    assert errors_selector(state) == []
    assert log_selector(empty_state) is None
    assert errors_selector(empty_state) is None

    detail_sync(None)
    log_sync(None)
    errors_sync(None)
    detail_sync(service)
    log_sync(logging.INFO)
    errors_sync([])

    assert len(recording_store.actions) == 3
