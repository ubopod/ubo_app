"""Tests for `BlockingWorker`.

Cancelling an await cannot stop a thread, and service cleanup cancels every
teardown coroutine after a grace period. So the guarantee this has to provide —
that two service instances never drive the same hardware at once — cannot rest
on shutdown finishing in time.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from ubo_app.utils.blocking_worker import BlockingWorker


async def test_calls_run_on_one_thread() -> None:
    """A single worker is what serializes access to the bus."""
    worker = BlockingWorker('test-serialization')
    threads = {await worker.run(threading.get_ident) for _ in range(5)}

    assert len(threads) == 1


async def test_a_restarted_instance_shares_the_same_thread() -> None:
    """The point of the process-global worker.

    A restarted service must not be able to touch the hardware while the
    previous instance's call is still running — and it cannot, because the two
    share one FIFO queue rather than racing on two threads.
    """
    first = BlockingWorker('test-restart')
    before = await first.run(threading.get_ident)
    await first.aclose()

    second = BlockingWorker('test-restart')
    after = await second.run(threading.get_ident)

    assert before == after


async def test_calls_are_serialized_not_interleaved() -> None:
    """Two overlapping awaits must not both be inside the bus at once."""
    worker = BlockingWorker('test-overlap')
    inside = 0
    peak = 0
    lock = threading.Lock()

    def _work() -> None:
        nonlocal inside, peak
        with lock:
            inside += 1
            peak = max(peak, inside)
        # Long enough that a second worker thread would overlap here.
        threading.Event().wait(0.02)
        with lock:
            inside -= 1

    await asyncio.gather(*(worker.run(_work) for _ in range(4)))

    assert peak == 1


async def test_a_closed_worker_refuses_further_work() -> None:
    """The thread outlives the service, so a stopped instance must stop feeding it.

    A queued reading would otherwise dispatch into a torn-down store.
    """
    worker = BlockingWorker('test-closed')
    await worker.aclose()

    with pytest.raises(RuntimeError, match='closed'):
        await worker.run(threading.get_ident)


async def test_aclose_waits_for_queued_work() -> None:
    """The drain is a no-op behind the queue, so it can only run after it."""
    worker = BlockingWorker('test-drain')
    finished: list[str] = []

    def _slow() -> None:
        threading.Event().wait(0.05)
        finished.append('slow')

    task = asyncio.ensure_future(worker.run(_slow))
    await asyncio.sleep(0)
    await worker.aclose()

    assert finished == ['slow']
    await task


async def test_a_call_that_blows_its_deadline_raises() -> None:
    """Without a deadline a wedged driver blocks the caller forever.

    `wait_for` would not do it: it cancels what it awaits and then waits for
    that cancellation, and a *running* executor future cannot be cancelled — so
    it would block for as long as the wedged call. Waiting *on* the future
    without touching it is what lets the await return promptly.
    """
    worker = BlockingWorker('test-deadline')
    release = threading.Event()

    def _wedged() -> None:
        release.wait(5)

    try:
        with pytest.raises(TimeoutError):
            await worker.run(_wedged, deadline=0.05)
    finally:
        release.set()


async def test_a_wedged_worker_refuses_work_until_the_call_returns() -> None:
    """Queueing behind a stuck thread just accumulates dead work.

    But wedged is a verdict on the thread, not a life sentence: the moment the
    overdue call finally returns, the thread has proven itself alive, and a
    (possibly restarted) service must be able to use it again.
    """
    worker = BlockingWorker('test-wedged')
    release = threading.Event()

    def _wedged() -> None:
        release.wait(5)

    try:
        with pytest.raises(TimeoutError):
            await worker.run(_wedged, deadline=0.05)

        # Still stuck: nothing queued behind the overdue call can run.
        with pytest.raises(RuntimeError, match='wedged'):
            await worker.run(threading.get_ident)

        # And a restarted service sees the same verdict — it is the same thread.
        with pytest.raises(RuntimeError, match='wedged'):
            await BlockingWorker('test-wedged').run(threading.get_ident)
    finally:
        release.set()

    # The overdue call has now returned; the worker thread clears the wedge as
    # soon as it notices, and both instances are usable again.
    async with asyncio.timeout(5):
        while True:
            try:
                assert await worker.run(threading.get_ident)
                break
            except RuntimeError:
                await asyncio.sleep(0.01)
    assert await BlockingWorker('test-wedged').run(threading.get_ident)


async def test_closing_a_wedged_worker_does_not_hang() -> None:
    """The drain sits behind the wedged call and would never run."""
    worker = BlockingWorker('test-wedged-close')
    release = threading.Event()

    def _wedged() -> None:
        release.wait(5)

    try:
        with pytest.raises(TimeoutError):
            await worker.run(_wedged, deadline=0.05)

        async with asyncio.timeout(1):
            await worker.aclose()
    finally:
        release.set()


async def test_a_task_raising_timeout_error_is_not_a_blown_deadline() -> None:
    """The failure is the task's, not the worker's.

    Plenty of blocking calls raise `TimeoutError` themselves — a driver giving
    up on a bus read, a socket with its own timeout. Treating that as a wedged
    thread would retire a perfectly healthy worker for the life of the process,
    taking every later reading with it.
    """
    worker = BlockingWorker('test-task-timeout')

    def _gives_up() -> None:
        msg = 'sensor did not answer'
        raise TimeoutError(msg)

    with pytest.raises(TimeoutError, match='sensor did not answer'):
        await worker.run(_gives_up)

    assert await worker.run(threading.get_ident)


async def test_a_cancelled_call_does_not_wedge_the_worker() -> None:
    """Service teardown cancels whatever is still awaiting.

    Cancellation is not a blown deadline: the next instance shares this thread
    and must still be able to use it. The thread runs on regardless, so its
    outcome is consumed on the way out — an unretrieved exception would surface
    later from asyncio, detached from the service it came from.
    """
    worker = BlockingWorker('test-cancelled')
    started = threading.Event()
    release = threading.Event()

    def _slow_failure() -> None:
        started.set()
        release.wait(5)
        msg = 'bus fell over'
        raise RuntimeError(msg)

    task = asyncio.ensure_future(worker.run(_slow_failure))
    await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    release.set()
    # The worker is still usable: nothing here was a deadline.
    assert await worker.run(threading.get_ident)


async def test_the_worker_thread_is_a_daemon() -> None:
    """A call that never returns must not hold the process open at exit.

    `ThreadPoolExecutor` joins its threads during interpreter shutdown, so a
    wedged driver would block a graceful shutdown — defeating the deadline that
    exists precisely to survive one. The deadline only frees the *caller*;
    daemonising is what frees the process.
    """
    worker = BlockingWorker('test-daemon')
    identity = await worker.run(threading.get_ident)

    thread = next(
        candidate
        for candidate in threading.enumerate()
        if candidate.ident == identity
    )
    assert thread.daemon


async def test_a_cancelled_call_never_reaches_the_hardware() -> None:
    """Queued work belongs to the caller that queued it.

    A service being restarted is cancelled while its readings sit behind the
    current call. Running them anyway would have a *stopped* instance driving
    the bus the new one has already taken over.
    """
    worker = BlockingWorker('test-skip-cancelled')
    release = threading.Event()
    ran: list[str] = []

    def _blocks() -> None:
        release.wait(5)
        ran.append('first')

    def _must_not_run() -> None:
        ran.append('second')

    first = asyncio.ensure_future(worker.run(_blocks))
    second = asyncio.ensure_future(worker.run(_must_not_run))
    # Both queued before either can finish.
    await asyncio.sleep(0)

    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second

    release.set()
    await first
    # A third call proves the worker got past the skipped one.
    await worker.run(threading.get_ident)

    assert ran == ['first']
