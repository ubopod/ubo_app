"""Fixture for loading services and waiting for them to be ready."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence, TypeAlias

import pytest

if TYPE_CHECKING:
    from tests.conftest import WaitFor

LoadServices: TypeAlias = Callable[[Sequence[str]], None]


@pytest.fixture()
def load_services(wait_for: WaitFor) -> LoadServices:
    """Load services and wait for them to be ready."""

    def load_services_and_wait(
        service_ids: Sequence[str],
    ) -> None:
        from ubo_app.load_services import load_services

        load_services(service_ids)

        @wait_for
        def check() -> None:
            from ubo_app.load_services import REGISTERED_PATHS

            for service_id in service_ids:
                assert any(
                    service.service_id == service_id and service.is_alive()
                    for service in REGISTERED_PATHS.values()
                ), f'{service_id} not loaded'

        check()

    return load_services_and_wait
