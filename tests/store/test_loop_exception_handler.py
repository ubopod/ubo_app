"""Tests for the asyncio loop exception handler's service-error attribution.

Two regression concerns are covered:

1. asyncio emits "Task was destroyed but it is pending!" from ``Task.__del__``
   during garbage collection, invoking the loop exception handler with a context
   that has *no* exception object. Such benign diagnostics must be logged but never
   recorded as a service error (they would otherwise pollute the deterministic store
   snapshot).

2. ``Task.__del__`` / ``Future.__del__`` run on whichever thread triggers the GC, so
   ``threading.current_thread()`` is the wrong source for attribution. The handler is
   bound to its loop's *owner* thread at ``set_exception_handler`` time and must
   attribute the error to that owner — not to the executing thread. A loop with no
   owning service (scheduler/worker) binds a thread without a ``service_id``, so its
   errors resolve to ``None`` and are not charged to any service.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

from ubo_app.utils import error_handlers

if TYPE_CHECKING:
    import threading

    import pytest


class _FakeServiceThread:
    """Stand-in for a service worker thread carrying a ``service_id``."""

    # ``name`` is read by the stdlib logging machinery via ``current_thread()``.
    name = 'infrared'
    service_id = 'infrared'
    label = 'Infrared'
    path = None


class _FakeCameraThread:
    """A second service thread, used to prove attribution follows the owner."""

    name = 'camera'
    service_id = 'camera'
    label = 'Camera'
    path = None


class _FakeNonServiceThread:
    """Stand-in for the scheduler/worker thread: it has no ``service_id``."""

    name = 'Scheduler Thread'
    label = None
    path = None


def _as_thread(obj: object) -> threading.Thread:
    """Treat a test stand-in as a ``threading.Thread`` for the handler signature."""
    return cast('threading.Thread', obj)


def _capture_reports(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``report_service_error`` with a recorder and return the record list."""
    reports: list[dict[str, Any]] = []
    monkeypatch.setattr(
        error_handlers,
        'report_service_error',
        lambda **kwargs: reports.append(kwargs),
    )
    return reports


def _fake_current_thread(
    monkeypatch: pytest.MonkeyPatch,
    thread: object,
) -> None:
    monkeypatch.setattr(
        error_handlers.threading,
        'current_thread',
        lambda: thread,
    )


def test_task_destroyed_warning_is_not_a_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A context without an exception must not be reported as a service error."""
    reports = _capture_reports(monkeypatch)
    _fake_current_thread(monkeypatch, _FakeServiceThread())

    loop = asyncio.new_event_loop()
    try:
        error_handlers.loop_exception_handler(
            loop,
            {
                'message': 'Task was destroyed but it is pending!',
                'task': '<Task pending name=...>',
            },
        )
    finally:
        loop.close()

    assert reports == []


def test_genuine_exception_is_reported_via_current_thread_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no bound owner, attribution falls back to the current thread."""
    reports = _capture_reports(monkeypatch)
    _fake_current_thread(monkeypatch, _FakeServiceThread())

    exception = RuntimeError('boom')
    loop = asyncio.new_event_loop()
    try:
        error_handlers.loop_exception_handler(
            loop,
            {'message': 'Unhandled exception in task', 'exception': exception},
        )
    finally:
        loop.close()

    assert len(reports) == 1
    assert reports[0]['service_id'] == 'infrared'
    assert reports[0]['exception'] is exception


def test_owner_overrides_current_thread_for_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A GC-time error is charged to the loop's owner, not the executing thread."""
    reports = _capture_reports(monkeypatch)
    # The GC happened to run on the 'infrared' service's thread...
    _fake_current_thread(monkeypatch, _FakeServiceThread())

    # ...but the loop that owns the dying task belongs to 'camera'.
    exception = RuntimeError('boom')
    loop = asyncio.new_event_loop()
    try:
        error_handlers.loop_exception_handler(
            loop,
            {'message': 'Task exception was never retrieved', 'exception': exception},
            owner=_as_thread(_FakeCameraThread()),
        )
    finally:
        loop.close()

    assert len(reports) == 1
    assert reports[0]['service_id'] == 'camera'


def test_owner_without_service_id_is_not_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error on the scheduler/worker loop (no owning service) is not reported.

    This is the "Future exception was never retrieved on the scheduler loop" case:
    even with a real exception present, a loop whose owner carries no ``service_id``
    must not have the error charged to whatever service triggered the GC.
    """
    reports = _capture_reports(monkeypatch)
    # GC ran on a real service thread...
    _fake_current_thread(monkeypatch, _FakeServiceThread())

    exception = RuntimeError('boom')
    loop = asyncio.new_event_loop()
    try:
        error_handlers.loop_exception_handler(
            loop,
            {'message': 'Task exception was never retrieved', 'exception': exception},
            owner=_as_thread(_FakeNonServiceThread()),
        )
    finally:
        loop.close()

    assert reports == []
