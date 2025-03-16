"""Fixture for loading services and waiting for them to be ready."""

from __future__ import annotations

import asyncio
from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
    cast,
    overload,
)

import pytest
from tenacity import wait_fixed

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


@pytest.fixture
def load_services(wait_for: WaitFor) -> Generator[LoadServices, None, None]:
    """Load services and wait for them to be ready."""
    from ubo_app.service_thread import REGISTERED_PATHS

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
        def check() -> None:
            for service_id in list(ids):
                assert any(
                    service.service_id == service_id
                    for service in REGISTERED_PATHS.values()
                ), f'{service_id} not loaded'
                assert any(
                    service.service_id == service_id
                    for service in REGISTERED_PATHS.values()
                ), f'{service_id} not alive'
                assert any(
                    service.service_id == service_id and service.is_started
                    for service in REGISTERED_PATHS.values()
                ), f'{service_id} not started'

                ids.remove(service_id)

        def stop(*, timeout: float | None = None) -> Coroutine[None, None, None]:
            @wait_for(run_async=cast('Literal[True]', run_async), timeout=timeout)
            def _() -> None:
                for service in REGISTERED_PATHS.values():
                    if service.service_id in service_ids:
                        assert not service.is_alive()
                REGISTERED_PATHS.clear()

            return _()

        result = check()

        if asyncio.iscoroutine(result):

            async def wrapper() -> AsyncUnloadWaiter:
                await result
                return cast('AsyncUnloadWaiter', stop)

            return wrapper()

        return cast('UnloadWaiter', stop)

    yield cast('LoadServices', load_services_and_wait)

    REGISTERED_PATHS.clear()
