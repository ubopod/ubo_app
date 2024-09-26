"""Fixture for loading services and waiting for them to be ready."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
    cast,
    overload,
)

import pytest

if TYPE_CHECKING:
    from collections.abc import Coroutine, Generator, Sequence

    from tests.conftest import WaitFor


class LoadServices(Protocol):
    """Load services and wait for them to be ready."""

    @overload
    def __call__(
        self: LoadServices,
        service_ids: Sequence[str],
        *,
        timeout: float | None = None,
        delay: float = 0.4,
    ) -> None: ...

    @overload
    def __call__(
        self: LoadServices,
        service_ids: Sequence[str],
        *,
        run_async: Literal[True],
        timeout: float | None = None,
        delay: float = 0.4,
    ) -> Coroutine[None, None, None]: ...


@pytest.fixture
def load_services(wait_for: WaitFor) -> Generator[LoadServices, None, None]:
    """Load services and wait for them to be ready."""
    from ubo_app.load_services import REGISTERED_PATHS

    def load_services_and_wait(
        service_ids: Sequence[str],
        *,
        run_async: bool = False,
        timeout: float | None = None,
        delay: float = 0.4,
    ) -> Coroutine[None, None, None] | None:
        from ubo_app.load_services import load_services

        load_services(service_ids, delay=delay)

        @wait_for(run_async=cast(Literal[True], run_async), timeout=timeout)
        def check() -> None:
            for service_id in service_ids:
                assert any(
                    service.service_id == service_id and service.is_alive()
                    for service in REGISTERED_PATHS.values()
                ), f'{service_id} not loaded'

        return check()

    yield cast(LoadServices, load_services_and_wait)

    REGISTERED_PATHS.clear()
