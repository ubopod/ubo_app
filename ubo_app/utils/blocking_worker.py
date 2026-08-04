"""One background thread owning one blocking resource, e.g. an I²C bus.

Separate from `ubo_app.utils.async_` on purpose: everything here is about a
*thread's* lifecycle, which does not follow the event loop's — a thread cannot
be cancelled, cannot be interrupted, and outlives the service that started it.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import queue
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

from typing_extensions import TypeVar

from ubo_app.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar('T', infer_variance=True)


# A fallback only. How long is too long is a property of the resource, so the
# owner of a worker is expected to say — see `BlockingWorker.__init__`.
DEFAULT_DEADLINE = 60


class _Job(NamedTuple):
    """One call to make on the worker thread, and where to put the outcome.

    `abandoned` is a token rather than a look at `future`: an `asyncio.Future`
    may only be touched from its own loop, and this is read from the worker
    thread. It is what stops a queued call running for a caller that has
    already given up — during a restart that is a *stopped* service instance
    reaching for the hardware the new one is now driving.
    """

    call: Callable[[], Any]
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future
    abandoned: threading.Event


def _settle(
    future: asyncio.Future,
    result: Any,  # noqa: ANN401
    exception: BaseException | None,
) -> None:
    # Already cancelled means the caller gave up — on a blown deadline, or
    # because it was itself cancelled. Its outcome has nowhere to go, and
    # nothing is owed to a cancelled future, so the result is simply dropped
    # rather than left unretrieved for asyncio to complain about later.
    if future.done():
        return
    if exception is not None:
        future.set_exception(exception)
    else:
        future.set_result(result)


def _serve(worker: _SharedWorker) -> None:
    """Run queued calls forever, one at a time."""
    while True:
        job = worker.jobs.get()
        if job.abandoned.is_set():
            # Checked here, immediately before the call, because the wait for
            # the job ahead of this one is exactly when a caller gives up.
            continue
        try:
            result = job.call()
        except BaseException as exception:  # noqa: BLE001
            outcome, error = None, exception
        else:
            outcome, error = result, None
        # Finishing a call proves this thread is not stuck, so a blown-deadline
        # verdict recorded while it was running is stale: the overdue call has
        # returned after all, and the worker can accept work again.
        if worker.wedged:
            worker.wedged = False
            logger.info(
                'Blocking worker recovered; the overdue call returned',
                extra={'worker': worker.name},
            )
        # A `RuntimeError` here means the loop this call belonged to is gone —
        # the service was stopped while its work was still queued. Nobody is
        # waiting for the answer.
        with contextlib.suppress(RuntimeError):
            job.loop.call_soon_threadsafe(_settle, job.future, outcome, error)


@dataclass
class _SharedWorker:
    """The process-wide thread for one resource, and whether it is still usable."""

    name: str
    jobs: queue.SimpleQueue[_Job] = field(default_factory=queue.SimpleQueue)
    # Set when a call blew its deadline. The thread cannot be reclaimed — Python
    # has no way to interrupt it — so this stays true for as long as the overdue
    # call is still running; the thread clears it the moment it finishes a call,
    # which is proof it is alive again.
    wedged: bool = False


# One thread per name, for the lifetime of the process. See `BlockingWorker`.
_blocking_workers: dict[str, _SharedWorker] = {}
# Guards get-or-create: two service instances racing to attach to one name must
# not each start a consumer thread on the same queue.
_blocking_workers_lock = threading.Lock()


class BlockingWorker:
    """One background thread owning one blocking resource, e.g. a bus.

    Cancelling an await does **not** stop a thread — Python cannot interrupt
    one — and service cleanup gives every teardown coroutine a bounded grace
    period before cancelling it (`service_thread.py`). So "wait for the worker
    to finish" is a promise this cannot keep: a slow or wedged I²C call outlives
    the timeout, the service reports itself stopped, and a restarted instance
    starts driving the same hardware.

    So the thread is **process-global per name** rather than owned by one
    service instance. A restart reuses the same worker, which makes overlapping
    hardware access impossible by construction instead of dependent on shutdown
    finishing in time: leftover work from the previous instance simply sits
    ahead of the new instance's in the same FIFO queue.

    `aclose()` then drains rather than joins-and-retires, and it is safe for it
    to be cut short.

    The thread is a **daemon**, and that is the whole reason this does not use a
    `ThreadPoolExecutor`: the pool's threads are joined during interpreter
    shutdown, so a driver that never returns would hold the whole process open
    at exit — defeating the deadline that exists precisely to survive that.
    """

    def __init__(self, name: str, *, deadline: float = DEFAULT_DEADLINE) -> None:
        """Attach to the process-wide worker for `name`, starting it if new.

        `deadline` is the default for every `run` on this instance. It belongs
        to whoever owns the resource: what counts as wedged depends on what the
        calls do, not on this module.
        """
        self._name = name
        self._deadline = deadline
        self._closed = False
        with _blocking_workers_lock:
            worker = _blocking_workers.get(name)
            if worker is None:
                worker = _blocking_workers[name] = _SharedWorker(name)
                threading.Thread(
                    target=_serve,
                    args=(worker,),
                    name=name,
                    daemon=True,
                ).start()
        self._worker = worker

    def _submit(
        self,
        call: Callable[[], Any],
    ) -> tuple[asyncio.Future, threading.Event]:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        abandoned = threading.Event()
        self._worker.jobs.put(
            _Job(call=call, loop=loop, future=future, abandoned=abandoned),
        )
        return future, abandoned

    async def run(
        self,
        task: Callable[..., T],
        *args: object,
        deadline: float | None = None,
    ) -> T:
        """Run `task` on the worker and return its result.

        `deadline` defaults to the one this worker was constructed with.

        Raises:
            RuntimeError: If this instance is closed — the thread outlives the
                service, so a stopped instance must stop feeding it, or a queued
                reading dispatches into a torn-down store — or if the worker is
                wedged.
            TimeoutError: If `task` blows its `deadline`, at which point the
                worker is marked wedged until the overdue call returns.

        """
        if self._closed:
            msg = f'{self._name} is closed'
            raise RuntimeError(msg)
        if self._worker.wedged:
            msg = f'{self._name} is wedged; a previous call never returned'
            raise RuntimeError(msg)

        if deadline is None:
            deadline = self._deadline

        future, abandoned = self._submit(functools.partial(task, *args))

        # `asyncio.wait` rather than `wait_for`, for two reasons. It reports
        # *whether* the future finished instead of raising, so a `TimeoutError`
        # coming out of `task` itself — an I²C driver giving up, say — stays an
        # ordinary failure rather than being mistaken for a blown deadline and
        # condemning the worker. And it leaves the future alone, where
        # `wait_for` would cancel it and then *await* that cancellation, which
        # a running call cannot honour.
        try:
            done, _ = await asyncio.wait({future}, timeout=deadline)
        except asyncio.CancelledError:
            abandoned.set()
            future.cancel()
            raise

        if future not in done:
            # The thread is unreclaimable, so the worker is out of service:
            # queueing more work behind the overdue call would just accumulate
            # calls that cannot run until — unless — it returns. The worker
            # thread clears the flag if it ever does.
            self._worker.wedged = True
            # The call itself is already running and cannot be stopped; this
            # only matters for the vanishingly rare case where it had not
            # started yet.
            abandoned.set()
            future.cancel()
            logger.error(
                'Blocking worker wedged; no further work accepted until the '
                'overdue call returns',
                extra={'worker': self._name, 'deadline': deadline},
            )
            msg = f'{self._name} exceeded its {deadline}s deadline'
            raise TimeoutError(msg)

        return future.result()

    async def aclose(self) -> None:
        """Stop feeding the worker, then wait for what is already queued.

        The drain is a no-op submitted behind the existing work: one thread and
        a FIFO queue mean it can only run once everything before it has. If the
        cleanup timeout cuts this short it costs nothing — the next instance
        shares this same thread either way.
        """
        self._closed = True
        if self._worker.wedged:
            # The drain would sit behind the overdue call for who knows how
            # long, and a stopping service cannot wait on that.
            return
        future, _ = self._submit(lambda: None)
        await future
