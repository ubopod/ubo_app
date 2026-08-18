"""Tests for stopping a service thread that never reached its event loop.

`UboServiceThread.loop` is only bound once `run` starts on the new thread. A
service registered but never started has none, and `stop_services` walks every
service in a single loop — so raising there strands every service after it.

Regression test for UBO-APP-KB.
"""

from __future__ import annotations

from pathlib import Path

from ubo_app.service_thread import UboServiceThread


def _make_thread() -> UboServiceThread:
    """Build a service thread without ever starting it."""
    return UboServiceThread(Path('/nonexistent/000-never-started'))


class TestStopBeforeRun:
    """Tests for `UboServiceThread.stop` before `run` binds the loop."""

    def test_no_loop_attribute_before_run(self) -> None:
        """Guard the premise: `loop` really is unbound until `run`."""
        assert not hasattr(_make_thread(), 'loop')

    def test_stop_does_not_raise(self) -> None:
        """Stopping a never-started service is a no-op, not an AttributeError."""
        _make_thread().stop()

    def test_stop_is_idempotent(self) -> None:
        """Repeated stops stay harmless."""
        thread = _make_thread()
        thread.stop()
        thread.stop()


class TestStopWithLoop:
    """Tests for `UboServiceThread.stop` once a loop exists."""

    def test_stop_schedules_shutdown(self) -> None:
        """A service with a loop still gets its shutdown scheduled."""
        thread = _make_thread()
        calls: list[object] = []

        class _FakeLoop:
            def call_soon_threadsafe(
                self,
                callback: object,
                *args: object,
            ) -> None:
                calls.append((callback, args))

            def create_task(self, coro: object) -> None:
                """Stand in for the real loop's task factory."""

        thread.loop = _FakeLoop()  # pyright: ignore[reportAttributeAccessIssue]
        thread.shutdown = lambda: None  # pyright: ignore[reportAttributeAccessIssue]

        thread.stop()

        assert len(calls) == 1
