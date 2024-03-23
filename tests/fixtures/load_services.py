"""Fixture for loading services and waiting for them to be ready."""

from __future__ import annotations

from typing import TYPE_CHECKING, Coroutine, Literal, Protocol, Sequence, cast, overload

import pytest

if TYPE_CHECKING:
    from tests.conftest import WaitFor


class LoadServices(Protocol):
    """Load services and wait for them to be ready."""

    @overload
    def __call__(
        self: LoadServices,
        service_ids: Sequence[str],
    ) -> None: ...

    @overload
    def __call__(
        self: LoadServices,
        service_ids: Sequence[str],
        *,
        run_async: Literal[True],
    ) -> Coroutine[None, None, None]: ...


@pytest.fixture()
def load_services(wait_for: WaitFor) -> LoadServices:
    """Load services and wait for them to be ready."""

    def load_services_and_wait(
        service_ids: Sequence[str],
        *,
        run_async: bool = False,
    ) -> Coroutine[None, None, None] | None:
        from ubo_app.load_services import load_services

        load_services(service_ids)

        @wait_for(run_async=cast(Literal[True], run_async))
        def check() -> None:
            from ubo_app.load_services import REGISTERED_PATHS

            for service_id in service_ids:
                assert any(
                    service.service_id == service_id and service.is_alive()
                    for service in REGISTERED_PATHS.values()
                ), f'{service_id} not loaded'

        return check()

    return cast(LoadServices, load_services_and_wait)
