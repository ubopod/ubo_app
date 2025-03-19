"""Tests for overridden subscribe_event method in service thread."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import (  # pyright: ignore [reportMissingModuleSource]
        ReducerRegistrar,
    )

    from tests.fixtures import AppContext, LoadServices
    from ubo_app.utils.types import Subscriptions


async def test_subscribe_event_runs_handler_in_service_thread(
    app_context: AppContext,
    load_services: LoadServices,
) -> None:
    """Test that the handler for a subscribe event runs in the service thread."""
    import asyncio
    from pathlib import Path
    from threading import current_thread

    from immutable import Immutable
    from redux import (
        BaseAction,
        CompleteReducerResult,
        InitAction,
        InitializationActionError,
        ReducerResult,
    )

    from ubo_app.service_thread import (
        SERVICE_PATHS_BY_ID,
        SERVICES_BY_PATH,
        UboServiceThread,
    )
    from ubo_app.store.core.types import MainAction, MainEvent

    class DummyEvent(MainEvent): ...

    class DummyAction(MainAction): ...

    class DummyState(Immutable): ...

    app_context.set_app()

    from ubo_app.store.main import store

    result: asyncio.Future[bool] = asyncio.Future()

    def check() -> None:
        thread = current_thread()
        result.set_result(thread is service_thread)

    def reducer(
        state: DummyState | None,
        action: BaseAction,
    ) -> ReducerResult[DummyState, None, DummyEvent]:
        if state is None:
            if isinstance(action, InitAction):
                return DummyState()
            raise InitializationActionError(action)

        if isinstance(action, DummyAction):
            return CompleteReducerResult(state=state, events=[DummyEvent()])

        return state

    def service_setup(register_reducer: ReducerRegistrar) -> Subscriptions:
        register_reducer(reducer)
        return [store.subscribe_event(DummyEvent, check)]

    service_thread = UboServiceThread(path=Path('/ubo-services/test'))
    service_thread.register(
        service_id='test',
        label='Test Service',
        setup=service_setup,
    )
    SERVICES_BY_PATH[service_thread.path] = service_thread
    SERVICE_PATHS_BY_ID[service_thread.service_id] = service_thread.path

    unload_waiter = await load_services(service_ids=['test'], run_async=True)

    store.dispatch(DummyAction())

    assert await result, 'handler for subscribe event did not run in service thread'

    await unload_waiter()
