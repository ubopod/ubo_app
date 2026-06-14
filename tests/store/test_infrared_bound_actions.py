"""Unit tests for infrared key→action binding.

Covers the pure infrared reducer decision logic (registered-device-first
dispatch, replay-only suppression, keypad fallback, auto-enable receive), the
bindable-actions registry, ``InfraredDevice`` persistence shape, and the
infrared service's bound-action event handler.

The reducer and setup live in a hyphenated service directory, so they are loaded
by file path (mirroring ``tests/navigation/test_keypad_reducer.py``). No store,
autorun, or hardware is involved.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from redux import CompleteReducerResult

from ubo_app.store.core.bindable_actions import (
    BindableActionContext,
    clear_all_bindable_actions,
    get_bindable_action,
    get_bindable_actions,
    register_bindable_action,
    unregister_bindable_action,
)
from ubo_app.store.services.infrared import (
    InfraredAddDeviceAction,
    InfraredBoundActionTriggeredEvent,
    InfraredDevice,
    InfraredHandleReceivedCodeAction,
    InfraredSetShouldReceiveAction,
    InfraredState,
)
from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

if TYPE_CHECKING:
    from types import ModuleType

    from ubo_app.store.main import UboAction

_SERVICE_DIR = (
    Path(__file__).resolve().parents[2]
    / 'ubo_app'
    / 'services'
    / '090-infrared'
)


def _load_module(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SERVICE_DIR / filename)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_reducer_module = _load_module('infrared_reducer_under_test', 'reducer.py')
reducer = _reducer_module.reducer

_setup_module = _load_module('infrared_setup_under_test', 'setup.py')
handle_bound_action = _setup_module._handle_bound_action_triggered  # noqa: SLF001

# A code that is also a built-in keypad code (L1 press), so tests can prove a
# registered device takes precedence over the keypad fallback.
_L1_PRESS = ('necx', '0xbf10')


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Keep the module-level registry isolated between tests."""
    clear_all_bindable_actions()


def _receive(protocol: str, scancode: str) -> InfraredHandleReceivedCodeAction:
    return InfraredHandleReceivedCodeAction(protocol=protocol, scancode=scancode)


class TestReceivedCodeDispatch:
    """Behaviour of ``InfraredHandleReceivedCodeAction`` while receiving."""

    def test_bound_device_emits_event_over_keypad_fallback(self) -> None:
        """A registered+bound device fires its event, not the keypad action."""
        protocol, scancode = _L1_PRESS
        state = InfraredState(
            should_receive_keypad_actions=True,
            registered_devices=[
                InfraredDevice(
                    name='TV Power',
                    protocol=protocol,
                    scancode=scancode,
                    bound_action_key='assistant:toggle',
                ),
            ],
        )

        result = reducer(state, _receive(protocol, scancode))

        assert isinstance(result, CompleteReducerResult)
        events = list(result.events or ())
        assert len(events) == 1
        event = events[0]
        assert isinstance(event, InfraredBoundActionTriggeredEvent)
        assert event.bound_action_key == 'assistant:toggle'
        assert event.device_name == 'TV Power'
        # The keypad fallback must NOT also fire.
        assert not any(
            isinstance(action, KeypadKeyPressAction)
            for action in (result.actions or ())
        )

    def test_replay_only_device_suppresses_keypad_fallback(self) -> None:
        """A registered device with no binding does nothing on receive."""
        protocol, scancode = _L1_PRESS
        state = InfraredState(
            should_receive_keypad_actions=True,
            registered_devices=[
                InfraredDevice(
                    name='TV Power',
                    protocol=protocol,
                    scancode=scancode,
                    bound_action_key=None,
                ),
            ],
        )

        result = reducer(state, _receive(protocol, scancode))

        # No-op: returns plain state (no event, no keypad action).
        assert result is state

    def test_unregistered_keypad_code_still_falls_back(self) -> None:
        """An unregistered built-in code still triggers the keypad action."""
        protocol, scancode = _L1_PRESS
        state = InfraredState(should_receive_keypad_actions=True)

        result = reducer(state, _receive(protocol, scancode))

        assert isinstance(result, CompleteReducerResult)
        actions = list(result.actions or ())
        assert any(
            isinstance(action, KeypadKeyPressAction) and action.key is Key.L1
            for action in actions
        )

    def test_old_assistant_scancode_is_inert(self) -> None:
        """A former hardcoded assistant code now does nothing without a binding."""
        state = InfraredState(should_receive_keypad_actions=True)

        # ('necx', '0xbf04') used to be the hardcoded assistant-start code.
        result = reducer(state, _receive('necx', '0xbf04'))

        assert result is state


class TestAddDeviceAutoEnableReceive:
    """``InfraredAddDeviceAction`` carries fields and enables receive on bind."""

    def test_binding_a_key_enables_receive(self) -> None:
        """Adding a bound device while receive is off turns receive on."""
        state = InfraredState(should_receive_keypad_actions=False)

        result = reducer(
            state,
            InfraredAddDeviceAction(
                name='TV Power',
                protocol='necx',
                scancode='0x1234',
                description='turns the TV on/off',
                bound_action_key='assistant:toggle',
            ),
        )

        assert isinstance(result, CompleteReducerResult)
        device = result.state.registered_devices[-1]
        assert device.bound_action_key == 'assistant:toggle'
        assert device.description == 'turns the TV on/off'
        assert any(
            isinstance(action, InfraredSetShouldReceiveAction)
            and action.should_receive is True
            for action in (result.actions or ())
        )

    def test_replay_only_does_not_enable_receive(self) -> None:
        """Adding a replay-only device leaves the receive flag untouched."""
        state = InfraredState(should_receive_keypad_actions=False)

        result = reducer(
            state,
            InfraredAddDeviceAction(
                name='TV Power',
                protocol='necx',
                scancode='0x1234',
            ),
        )

        assert isinstance(result, CompleteReducerResult)
        assert result.state.registered_devices[-1].bound_action_key is None
        assert not any(
            isinstance(action, InfraredSetShouldReceiveAction)
            for action in (result.actions or ())
        )


class TestInfraredDevicePersistenceShape:
    """The device model round-trips the new optional fields."""

    def test_legacy_dict_loads_with_none_defaults(self) -> None:
        """A device persisted before this feature loads with None defaults."""
        legacy = {'name': 'Old', 'protocol': 'necx', 'scancode': '0x1'}
        device = InfraredDevice(**legacy)
        assert device.description is None
        assert device.bound_action_key is None

    def test_full_dict_loads_fields(self) -> None:
        """A device with the new fields persisted loads them back."""
        persisted = {
            'name': 'New',
            'protocol': 'necx',
            'scancode': '0x1',
            'description': 'desc',
            'bound_action_key': 'assistant:toggle',
        }
        device = InfraredDevice(**persisted)
        assert device.description == 'desc'
        assert device.bound_action_key == 'assistant:toggle'


def _dummy_factory(_ctx: BindableActionContext) -> UboAction:
    return InfraredSetShouldReceiveAction(should_receive=True)


class TestBindableRegistry:
    """The bindable-actions registry contract."""

    def test_register_and_get(self) -> None:
        """A registered action is retrievable; a missing key returns None."""
        register_bindable_action('a:one', 'Label One', _dummy_factory)
        bindable = get_bindable_action('a:one')
        assert bindable is not None
        assert bindable.label == 'Label One'
        assert get_bindable_action('missing') is None

    def test_duplicate_key_raises(self) -> None:
        """Registering an existing key without the flag raises."""
        register_bindable_action('a:one', 'Label One', _dummy_factory)
        with pytest.raises(ValueError, match='already registered'):
            register_bindable_action('a:one', 'Other', _dummy_factory)

    def test_duplicate_key_allowed_with_flag(self) -> None:
        """``allow_reregister`` replaces an existing key."""
        register_bindable_action('a:one', 'Label One', _dummy_factory)
        register_bindable_action(
            'a:one',
            'Renamed',
            _dummy_factory,
            allow_reregister=True,
        )
        bindable = get_bindable_action('a:one')
        assert bindable is not None
        assert bindable.label == 'Renamed'

    def test_duplicate_label_raises(self) -> None:
        """Reusing a label under a different key raises."""
        register_bindable_action('a:one', 'Shared', _dummy_factory)
        with pytest.raises(ValueError, match='already used'):
            register_bindable_action('a:two', 'Shared', _dummy_factory)

    def test_unregister_and_clear(self) -> None:
        """Unregister removes one entry; clear removes all."""
        register_bindable_action('a:one', 'Label One', _dummy_factory)
        register_bindable_action('a:two', 'Label Two', _dummy_factory)
        assert unregister_bindable_action('a:one') is True
        assert unregister_bindable_action('a:one') is False
        assert [b.key for b in get_bindable_actions()] == ['a:two']
        clear_all_bindable_actions()
        assert get_bindable_actions() == []

    def test_registration_order_preserved(self) -> None:
        """``get_bindable_actions`` returns entries in registration order."""
        register_bindable_action('a:one', 'One', _dummy_factory)
        register_bindable_action('a:two', 'Two', _dummy_factory)
        register_bindable_action('a:three', 'Three', _dummy_factory)
        assert [b.key for b in get_bindable_actions()] == [
            'a:one',
            'a:two',
            'a:three',
        ]


class _FakeStore:
    def __init__(self) -> None:
        self.dispatched: list[object] = []

    def dispatch(self, action: object) -> None:
        self.dispatched.append(action)


class TestBoundActionHandler:
    """The side-effect handler resolves the registry and dispatches."""

    def _event(self, key: str) -> InfraredBoundActionTriggeredEvent:
        return InfraredBoundActionTriggeredEvent(
            bound_action_key=key,
            protocol='necx',
            scancode='0x1',
            device_name='TV Power',
        )

    def test_valid_binding_dispatches(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A resolvable key dispatches the factory's action."""
        fake_store = _FakeStore()
        monkeypatch.setattr(_setup_module, 'store', fake_store)
        sentinel = InfraredSetShouldReceiveAction(should_receive=True)
        register_bindable_action('a:one', 'One', lambda _ctx: sentinel)

        handle_bound_action(self._event('a:one'))

        assert fake_store.dispatched == [sentinel]

    def test_missing_registry_entry_no_dispatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unresolvable key dispatches nothing (logged, not raised)."""
        fake_store = _FakeStore()
        monkeypatch.setattr(_setup_module, 'store', fake_store)

        handle_bound_action(self._event('a:missing'))

        assert fake_store.dispatched == []

    def test_factory_exception_is_caught(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A factory that raises is caught; nothing is dispatched."""
        fake_store = _FakeStore()
        monkeypatch.setattr(_setup_module, 'store', fake_store)

        def _boom(_ctx: BindableActionContext) -> UboAction:
            msg = 'boom'
            raise RuntimeError(msg)

        register_bindable_action('a:boom', 'Boom', _boom)

        # Must not raise.
        handle_bound_action(self._event('a:boom'))

        assert fake_store.dispatched == []
