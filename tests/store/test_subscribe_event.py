"""Tests for overridden subscribe_event method in service thread."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ubo_handle import Service  # pyright: ignore [reportMissingModuleSource]

    from tests.fixtures.app import AppContext
    from tests.fixtures.load_services import LoadServices
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

    from ubo_app.menu_app.menu import MenuApp
    from ubo_app.service_thread import (
        REGISTERED_PATHS,
        SERVICES_BY_ID,
        UboServiceThread,
    )
    from ubo_app.store.core.types import MainEvent

    class DummyEvent(MainEvent):
        """A dummy event for testing purposes."""

    class DummyState(Immutable):
        """A dummy state for testing purposes."""

    app = MenuApp()
    app_context.set_app(app)

    from ubo_app.store.main import store

    result: asyncio.Future[bool] = asyncio.Future()

    def check() -> None:
        thread = current_thread()
        result.set_result(thread is service_thread)

    def reducer(
        state: DummyState | None,
        action: BaseAction,
    ) -> ReducerResult[DummyState, None, DummyEvent]:
        if isinstance(action, InitAction):
            return CompleteReducerResult(
                state=DummyState(),
                events=[DummyEvent()],
            )

        if state is None:
            raise InitializationActionError(action)

        return state

    def service_setup(service: Service) -> Subscriptions:
        service.register_reducer(reducer)
        return [store.subscribe_event(DummyEvent, check)]

    service_thread = UboServiceThread(path=Path('/ubo-services/test'))
    service_thread.register(
        service_id='test',
        label='Test Service',
        setup=service_setup,
    )
    REGISTERED_PATHS[service_thread.path] = service_thread
    SERVICES_BY_ID[service_thread.service_id] = service_thread.path

    await load_services(service_ids=['test'], run_async=True)

    assert await result, 'handler for subscribe event did not run in service thread'
