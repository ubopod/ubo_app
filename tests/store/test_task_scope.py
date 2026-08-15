"""Tests for the MQTT service's `TaskScope`.

The project's `create_task` is fire-and-forget — it returns a `Handle` — so
anything that needs to `await` a task, or hand it to `asyncio.wait`, reaches for
`asyncio.create_task` and the task stops being visible to shutdown and to error
reporting. A *delayed* one then keeps running after its service has stopped and
can still act on the store.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
from pathlib import Path

import pytest

from tests.service_loader import load_service_modules

(task_scope,) = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '050-mqtt',
    'task_scope',
)
TaskScope = task_scope.TaskScope


async def _settle(predicate: object = None) -> None:
    """Let done-callbacks run.

    `add_done_callback` is scheduled with `call_soon`, so a single `sleep(0)`
    happens to be enough on an idle loop and is not once other tests are
    sharing it.
    """
    for _ in range(50):
        await asyncio.sleep(0)
        if predicate is not None and predicate():  # pyright: ignore[reportCallIssue]
            return


async def test_a_scoped_task_is_still_awaitable() -> None:
    """The whole point: ownership without giving up the `asyncio.Task`."""
    scope = TaskScope('test')

    async def _work() -> str:
        return 'done'

    task = scope.create(_work())

    assert isinstance(task, asyncio.Task)
    assert await task == 'done'


async def test_closing_the_scope_cancels_a_pending_task() -> None:
    """A delayed flush must not outlive the service that scheduled it."""
    scope = TaskScope('test')
    ran: list[bool] = []

    async def _later() -> None:
        await asyncio.sleep(10)
        ran.append(True)

    task = scope.create(_later())
    await scope.aclose()

    assert task.cancelled()
    assert ran == []


async def test_a_finished_task_is_forgotten() -> None:
    """Otherwise the scope is a leak: every task ever started, held forever."""
    scope = TaskScope('test')

    async def _work() -> None:
        return

    await scope.create(_work())
    await _settle(lambda: not scope._tasks)  # noqa: SLF001

    assert scope._tasks == set()  # noqa: SLF001


async def test_a_failing_task_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A detached task's exception otherwise goes nowhere the user can see."""
    # `importlib.import_module`, not `from ubo_app.utils import ...`: other
    # tests purge `sys.modules` without clearing the parent package's
    # attribute, so the plain form hands back a *stale* module while the late
    # import inside `_finished` re-imports a fresh one — and the patch lands on
    # the wrong object.
    error_handlers = importlib.import_module('ubo_app.utils.error_handlers')

    reported: list[object] = []
    monkeypatch.setattr(
        error_handlers,
        'report_service_error',
        lambda **kwargs: reported.append(kwargs.get('exception')),
    )
    scope = TaskScope('test')

    async def _boom() -> None:
        msg = 'boom'
        raise RuntimeError(msg)

    task = scope.create(_boom())
    with pytest.raises(RuntimeError):
        await task
    await _settle(lambda: bool(reported))

    assert [type(exception) for exception in reported] == [RuntimeError]


async def test_report_errors_false_stays_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For a task whose exception the caller re-raises itself.

    The MQTT session races several tasks and re-raises the first; reporting it
    here as well would count the same failure twice.
    """
    # `importlib.import_module`, not `from ubo_app.utils import ...`: other
    # tests purge `sys.modules` without clearing the parent package's
    # attribute, so the plain form hands back a *stale* module while the late
    # import inside `_finished` re-imports a fresh one — and the patch lands on
    # the wrong object.
    error_handlers = importlib.import_module('ubo_app.utils.error_handlers')

    reported: list[object] = []
    monkeypatch.setattr(
        error_handlers,
        'report_service_error',
        lambda **kwargs: reported.append(kwargs),
    )
    scope = TaskScope('test')

    async def _boom() -> None:
        msg = 'boom'
        raise RuntimeError(msg)

    task = scope.create(_boom(), report_errors=False)
    with pytest.raises(RuntimeError):
        await task
    await _settle()

    assert reported == []


async def test_cancelling_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown cancels everything; that is not something to report."""
    # `importlib.import_module`, not `from ubo_app.utils import ...`: other
    # tests purge `sys.modules` without clearing the parent package's
    # attribute, so the plain form hands back a *stale* module while the late
    # import inside `_finished` re-imports a fresh one — and the patch lands on
    # the wrong object.
    error_handlers = importlib.import_module('ubo_app.utils.error_handlers')

    reported: list[object] = []
    monkeypatch.setattr(
        error_handlers,
        'report_service_error',
        lambda **kwargs: reported.append(kwargs),
    )
    scope = TaskScope('test')

    async def _later() -> None:
        await asyncio.sleep(10)

    scope.create(_later())
    await scope.aclose()

    assert reported == []


async def test_a_task_started_from_a_cancelled_finally_is_refused() -> None:
    """`aclose` must not return leaving a live task behind.

    A cancelled task can reach back into the scope from its `finally`. Taking a
    snapshot of the task set and clearing it up front would let that new task
    slip through and outlive the service.
    """
    scope = TaskScope('test')
    escaped: list[asyncio.Task] = []

    async def _forever() -> None:
        await asyncio.sleep(10)

    async def _restarts() -> None:
        try:
            await asyncio.sleep(10)
        finally:
            with contextlib.suppress(RuntimeError):
                escaped.append(scope.create(_forever()))

    scope.create(_restarts())
    await asyncio.sleep(0)
    await scope.aclose()

    assert escaped == []
    assert scope._tasks == set()  # noqa: SLF001


async def test_a_closed_scope_refuses_new_tasks() -> None:
    """Explicitly, so a caller gets an error rather than a silent no-op."""
    scope = TaskScope('test')
    await scope.aclose()

    async def _work() -> None:
        return

    with pytest.raises(RuntimeError, match='closed'):
        scope.create(_work())
