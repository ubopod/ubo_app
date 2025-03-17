"""Fixture for loading services and waiting for them to be ready."""

from __future__ import annotations

import asyncio
import functools
from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
    cast,
    overload,
)

import pytest
from tenacity import RetryError, wait_fixed

from ubo_app.logger import logger
from ubo_app.service_thread import SERVICE_PATHS_BY_ID

if TYPE_CHECKING:
    from collections.abc import Coroutine, Generator, Sequence

    from tests.conftest import WaitFor


class UnloadWaiter(Protocol):
    """Wait for services to be unloaded."""

    def __call__(self, *, timeout: float | None = None) -> None:
        """Wait for services to be unloaded."""


class AsyncUnloadWaiter(Protocol):
    """Wait for services to be unloaded."""

    async def __call__(self, *, timeout: float | None = None) -> None:  # noqa: ASYNC109
        """Wait for services to be unloaded."""
        ...


class LoadServices(Protocol):
    """Load services and wait for them to be ready."""

    @overload
    def __call__(
        self: LoadServices,
        service_ids: Sequence[str],
        *,
        timeout: float | None = None,
        gap_duration: float = 0.4,
    ) -> UnloadWaiter: ...

    @overload
    def __call__(
        self: LoadServices,
        service_ids: Sequence[str],
        *,
        run_async: Literal[True],
        timeout: float | None = None,
        gap_duration: float = 0.4,
    ) -> Coroutine[None, None, AsyncUnloadWaiter]: ...


def _check_dangling_services(service_ids: Sequence[str]) -> None:
    from ubo_app.service_thread import SERVICES_BY_PATH

    for service in SERVICES_BY_PATH.values():
        if service.service_id in service_ids and service.is_alive():
            logger.exception(
                'Service is still alive after unload',
                extra={
                    'service_id': service.service_id,
                    'loop': service.loop,
                    'tasks': asyncio.all_tasks(service.loop),
                },
            )
            service.kill()


def _unload_waiter(
    *,
    service_ids: Sequence[str],
    wait_for: WaitFor,
    run_async: bool,
    timeout: float | None = None,
) -> Coroutine[None, None, None]:
    from ubo_app.service_thread import SERVICES_BY_PATH, stop_services

    services = [
        service
        for service in SERVICES_BY_PATH.values()
        if service.service_id in service_ids
    ]

    stop_services(service_ids)

    @wait_for(
        run_async=cast('Literal[True]', run_async),
        timeout=timeout,
        wait=wait_fixed(1),
    )
    def _() -> None:
        for service in services:
            assert not service.is_alive()

    try:
        result = _()
    except RetryError:
        _check_dangling_services(service_ids)
        raise
    else:
        if asyncio.iscoroutine(result):

            async def wrapper() -> None:
                try:
                    await result
                except RetryError:
                    _check_dangling_services(service_ids)
                    raise

            return wrapper()
        return result


@pytest.fixture
def load_services(wait_for: WaitFor) -> Generator[LoadServices, None, None]:
    """Load services and wait for them to be ready."""
    from ubo_app.service_thread import SERVICES_BY_PATH

    def load_services_and_wait(
        service_ids: Sequence[str],
        *,
        run_async: bool = False,
        timeout: float | None = None,
        gap_duration: float = 0.4,
    ) -> UnloadWaiter | Coroutine[None, None, AsyncUnloadWaiter]:
        from ubo_app.service_thread import load_services

        load_services(service_ids, gap_duration=gap_duration)
        ids = list(service_ids)

        @wait_for(
            run_async=cast('Literal[True]', run_async),
            timeout=timeout,
            wait=wait_fixed(1),
        )
        def load_waiter() -> None:
            for service_id in list(ids):
                assert any(
                    service.service_id == service_id
                    for service in SERVICES_BY_PATH.values()
                ), f'{service_id} not loaded'
                assert any(
                    service.service_id == service_id and service.is_alive()
                    for service in SERVICES_BY_PATH.values()
                ), f'{service_id} not alive'
                assert any(
                    service.service_id == service_id and service.is_started
                    for service in SERVICES_BY_PATH.values()
                ), f'{service_id} not started'

                ids.remove(service_id)

        result = load_waiter()

        unload_waiter = functools.partial(
            _unload_waiter,
            service_ids=service_ids,
            wait_for=wait_for,
            run_async=run_async,
        )

        if asyncio.iscoroutine(result):

            async def wrapper() -> AsyncUnloadWaiter:
                await result
                return cast('AsyncUnloadWaiter', unload_waiter)

            return wrapper()

        return cast('UnloadWaiter', unload_waiter)

    yield cast('LoadServices', load_services_and_wait)

    SERVICE_PATHS_BY_ID.clear()
