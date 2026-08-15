"""Unit tests for shared engine setup and background-run lifecycle behavior."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    import pytest


class _RecordingStore:
    """Minimal store double for lifecycle notifications and refresh actions."""

    def __init__(self) -> None:
        self.actions: list[object] = []

    def dispatch(self, *actions: object) -> None:
        """Record dispatched actions."""
        self.actions.extend(actions)


_STORE_MAIN_MODULE = 'ubo_app.store.main'
_BACKGROUND_MODULE = 'ubo_app.engines.abstraction.background_running_mixin'
_NEEDS_SETUP_MODULE = 'ubo_app.engines.abstraction.needs_setup_mixin'
_previous_store_main = sys.modules.get(_STORE_MAIN_MODULE)
_previous_background = sys.modules.get(_BACKGROUND_MODULE)
_previous_needs_setup = sys.modules.get(_NEEDS_SETUP_MODULE)
_fake_store_main = ModuleType(_STORE_MAIN_MODULE)
_fake_store_main.store = _RecordingStore()  # type: ignore[attr-defined]
sys.modules[_STORE_MAIN_MODULE] = _fake_store_main
background_module: ModuleType | None = None
needs_setup_module: ModuleType | None = None
try:
    background_module = importlib.import_module(_BACKGROUND_MODULE)
    needs_setup_module = importlib.import_module(_NEEDS_SETUP_MODULE)
finally:
    if _previous_store_main is None:
        del sys.modules[_STORE_MAIN_MODULE]
    else:
        sys.modules[_STORE_MAIN_MODULE] = _previous_store_main
    abstraction_package = sys.modules['ubo_app.engines.abstraction']
    if _previous_needs_setup is None:
        del sys.modules[_NEEDS_SETUP_MODULE]
        if (
            needs_setup_module is not None
            and getattr(abstraction_package, 'needs_setup_mixin', None)
            is needs_setup_module
        ):
            delattr(abstraction_package, 'needs_setup_mixin')
    if _previous_background is None:
        del sys.modules[_BACKGROUND_MODULE]
        if (
            background_module is not None
            and getattr(abstraction_package, 'background_running_mixin', None)
            is background_module
        ):
            delattr(abstraction_package, 'background_running_mixin')
assert background_module is not None
assert needs_setup_module is not None
loaded_background_module = background_module
loaded_needs_setup_module = needs_setup_module
BackgroundRunningMixin = loaded_background_module.BackgroundRunningMixin
NeedsSetupMixin = loaded_needs_setup_module.NeedsSetupMixin


class _Task:
    """Controllable asyncio-task double."""

    def __init__(
        self,
        *,
        cancelled: bool = False,
        exception: BaseException | None = None,
    ) -> None:
        self.cancelled_value = cancelled
        self.exception_value = exception
        self.cancel_called = False
        self.done_callbacks: list[Callable[[_Task], None]] = []

    def add_done_callback(self, callback: Callable[[_Task], None]) -> None:
        self.done_callbacks.append(callback)

    def cancel(self) -> None:
        self.cancel_called = True

    def cancelled(self) -> bool:
        return self.cancelled_value

    def exception(self) -> BaseException | None:
        return self.exception_value

    def finish(self) -> None:
        for callback in self.done_callbacks:
            callback(self)


class _BackgroundEngine(BackgroundRunningMixin):
    """Concrete background engine used by lifecycle tests."""

    def __init__(self) -> None:
        self.run_count = 0
        self.desired_running = False
        super().__init__()

    @property
    def name(self) -> str:
        return 'background-test'

    @property
    def label(self) -> str:
        return 'Background Test'

    async def _run(self) -> None:
        self.run_count += 1

    def should_be_running(self) -> bool:
        return self.desired_running


class _SetupBackgroundEngine(NeedsSetupMixin, BackgroundRunningMixin):
    """Background engine whose run method is guarded by setup state."""

    credential_secret_ids = ('first-key', 'second-key')

    def __init__(self, *, is_setup: bool) -> None:
        self.setup_value = is_setup
        self.setup_calls = 0
        self.clear_calls = 0
        super().__init__()

    @property
    def name(self) -> str:
        return 'setup-test'

    @property
    def label(self) -> str:
        return 'Setup Test'

    @property
    def not_setup_message(self) -> str:
        return 'Configure the engine first.'

    @property
    def is_setup(self) -> bool:
        return self.setup_value

    async def _setup(self) -> None:
        self.setup_calls += 1

    async def _run(self) -> None:
        return None

    def _clear_credentials(self) -> None:
        self.clear_calls += 1


class _AISetupEngine(NeedsSetupMixin, AIProviderMixin):
    """AI provider used to verify provider refresh callbacks."""

    def __init__(self) -> None:
        self.setup_calls = 0
        self.clear_calls = 0
        super().__init__()

    @property
    def name(self) -> str:
        return 'ai-setup-test'

    @property
    def label(self) -> str:
        return 'AI Setup Test'

    @property
    def not_setup_message(self) -> str:
        return 'Configure AI.'

    @property
    def is_setup(self) -> bool:
        return False

    async def _setup(self) -> None:
        self.setup_calls += 1

    def _clear_credentials(self) -> None:
        self.clear_calls += 1


def _install_store(
    monkeypatch: pytest.MonkeyPatch,
    store: _RecordingStore,
) -> None:
    """Make runtime-local store imports resolve to the supplied double."""
    fake_main = ModuleType(_STORE_MAIN_MODULE)
    fake_main.store = store  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, _STORE_MAIN_MODULE, fake_main)
    monkeypatch.setattr(loaded_background_module, 'store', store)


def test_run_is_idempotent_and_stop_cancels_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated run calls create one task and stop cancels that task."""
    task = _Task(cancelled=True)
    coroutines: list[Coroutine[object, object, object]] = []

    def _create_task(
        coroutine: Coroutine[object, object, object],
        callback: Callable[[_Task], None],
        **_kwargs: object,
    ) -> None:
        coroutines.append(coroutine)
        coroutine.close()
        callback(task)

    monkeypatch.setattr(loaded_background_module, 'create_task', _create_task)
    engine = _BackgroundEngine()

    assert engine.run() is True
    assert engine.run() is True
    engine.stop()
    task.finish()

    assert len(coroutines) == 1
    assert task.cancel_called is True
    assert engine._task is None  # noqa: SLF001
    assert engine._is_running is False  # noqa: SLF001


def test_failed_background_task_reports_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unhandled engine failures reach service reporting and user notification."""
    store = _RecordingStore()
    _install_store(monkeypatch, store)
    error = RuntimeError('engine failed')
    reports: list[BaseException | None] = []
    monkeypatch.setattr(
        loaded_background_module,
        'report_service_error',
        lambda *, exception: reports.append(exception),
    )
    engine = _BackgroundEngine()

    engine._task_done_callback(cast('object', _Task(exception=error)))  # noqa: SLF001

    assert reports == [error]
    notification = cast('SimpleNamespace', store.actions[0]).notification
    assert notification.title == 'background-test'
    assert 'An error occurred' in notification.content


def test_decide_running_state_starts_or_stops_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desired state starts an idle engine and cancels an undesired task."""
    task = _Task()

    def _create_task(
        coroutine: Coroutine[object, object, object],
        callback: Callable[[_Task], None],
        **_kwargs: object,
    ) -> None:
        coroutine.close()
        callback(task)

    monkeypatch.setattr(loaded_background_module, 'create_task', _create_task)
    engine = _BackgroundEngine()
    engine.desired_running = True
    engine.decide_running_state()
    engine.desired_running = False
    engine.decide_running_state()

    assert task.cancel_called is True


def test_checked_run_blocks_unconfigured_background_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unconfigured engine returns False and offers a setup notification."""
    from ubo_app.store.core.action_registry import clear_all_actions

    store = _RecordingStore()
    _install_store(monkeypatch, store)
    clear_all_actions()
    engine = _SetupBackgroundEngine(is_setup=False)

    try:
        assert engine.run() is False
    finally:
        clear_all_actions()

    notification = cast('SimpleNamespace', store.actions[0]).notification
    assert notification.id == 'ubo:engine-error:setup-test'
    assert notification.content == 'Configure the engine first.'
    assert notification.actions[0].label == 'Set Up'


def test_stored_credentials_checks_declared_secret_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credential presence is derived from declared secret IDs on disk."""
    from ubo_app.utils import secrets

    engine = _SetupBackgroundEngine(is_setup=False)
    values = {'first-key': None, 'second-key': 'configured'}
    monkeypatch.setattr(secrets, 'read_secret', values.get)

    assert engine.has_stored_credentials() is True
    values['second-key'] = None
    assert engine.has_stored_credentials() is False


def test_ai_setup_and_clear_credentials_refresh_provider_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI setup completion and credential deletion both refresh provider state."""
    store = _RecordingStore()
    _install_store(monkeypatch, store)
    tasks: list[_Task] = []

    def _create_task(
        coroutine: Coroutine[object, object, object],
        callback: Callable[[_Task], None] | None = None,
    ) -> None:
        coroutine.close()
        task = _Task()
        tasks.append(task)
        if callback is not None:
            callback(task)
            task.finish()

    monkeypatch.setattr(loaded_needs_setup_module, 'create_task', _create_task)
    engine = _AISetupEngine()

    engine.setup()
    engine.clear_credentials()

    assert len(tasks) == 1
    assert engine.clear_calls == 1
    assert [type(action).__name__ for action in store.actions] == [
        'AssistantUpdateProvidersAction',
        'AssistantUpdateProvidersAction',
    ]
