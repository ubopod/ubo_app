"""Test the general health of the application."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from redux_pytest.fixtures import StoreSnapshot, WaitFor
    from ubo_handle import (  # pyright: ignore [reportMissingModuleSource]
        ReducerRegistrar,
    )

    from tests.fixtures import AppContext, LoadServices, Stability
    from tests.fixtures.snapshot import WindowSnapshot
    from ubo_app.store.main import UboStore

MAX_EXPECTED_LISTENERS = 600
MAX_EXPECTED_EVENT_HANDLERS = 70


@pytest.mark.timeout(300)
async def test_all_services_register(
    app_context: AppContext,
    window_snapshot: WindowSnapshot,
    store_snapshot: StoreSnapshot,
    load_services: LoadServices,
    stability: Stability,
    wait_for: WaitFor,
    store: UboStore,
) -> None:
    """Test all services load."""
    from ubo_app.constants import CORE_SERVICE_IDS

    app_context.set_app()
    unload_waiter = await load_services(CORE_SERVICE_IDS, timeout=90, run_async=True)

    await stability(initial_wait=6, attempts=5, wait=2)

    from tenacity import wait_fixed

    @wait_for(run_async=True, timeout=20, wait=wait_fixed(1))
    def wait_for_docker_ready() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        docker_state = state.docker
        # ensure reducer registered and well-known images are present
        assert docker_state.combine_reducers_id
        # service status should have been determined
        from ubo_app.store.services.docker import DockerStatus

        assert docker_state.service.status != DockerStatus.UNKNOWN

    await wait_for_docker_ready()

    @wait_for(run_async=True, timeout=120, wait=wait_fixed(2))
    def wait_for_docker_menu_items() -> None:
        state = store._state  # noqa: SLF001
        assert state is not None
        # Verify the docker app is registered in the serializable registry
        assert 'docker:envoy_grpc' in state.main.registered_apps

    await wait_for_docker_menu_items()

    assert len(store._listeners) < MAX_EXPECTED_LISTENERS  # noqa: SLF001
    assert len(store._event_handlers) < MAX_EXPECTED_EVENT_HANDLERS  # noqa: SLF001

    await stability(initial_wait=10, attempts=5, wait=2)

    from tests.conftest import exclude_dynamic_menus

    store_snapshot.take(selector=exclude_dynamic_menus)
    window_snapshot.take()

    await unload_waiter(timeout=50)


async def test_reducer_barrier(
    app_context: AppContext,
    load_services: LoadServices,
) -> None:
    """Test all services load."""
    services_count = 10

    import asyncio
    import random
    from pathlib import Path

    from ubo_app.service_thread import (
        SERVICE_PATHS_BY_ID,
        SERVICES_BY_PATH,
        UboServiceThread,
    )
    from ubo_app.store.core.types import MainAction

    app_context.set_app()

    calls = []

    def reducer(
        state: None,
        action: MainAction,
    ) -> None:
        if isinstance(action, DummyAction):
            calls.append(action)
        return state

    class DummyAction(MainAction): ...

    async def service_setup(register_reducer: ReducerRegistrar) -> None:
        await asyncio.sleep(random.uniform(1, 5))  # noqa: S311
        register_reducer(reducer)

        from ubo_app.store.main import store

        store.dispatch(DummyAction())

    service_threads: list[UboServiceThread] = []

    for i in range(services_count):
        service_thread = UboServiceThread(path=Path(f'/ubo-services/test-{i}'))
        service_thread.register(
            service_id=f'test_{i}',
            label=f'Test Service - {i}',
            setup=service_setup,
        )
        SERVICES_BY_PATH[service_thread.path] = service_thread
        SERVICE_PATHS_BY_ID[service_thread.service_id] = service_thread.path

        service_threads.append(service_thread)

    unload_waiter = await load_services(
        service_ids=[f'test_{i}' for i in range(services_count)],
        run_async=True,
        gap_duration=0,
        timeout=10,
    )

    await unload_waiter()

    assert len(calls) == services_count * services_count, (
        f'All {services_count} services should have called the reducer x each action '
        f"""should have been passed to all the {services_count} reducers = {
            services_count * services_count
        } calls."""
    )
