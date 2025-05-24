# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import asyncio
import contextlib
import ctypes
import importlib
import importlib.abc
import importlib.util
import inspect
import logging
import sys
import threading
import traceback
import weakref
from collections import OrderedDict
from dataclasses import replace
from importlib.machinery import PathFinder, SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from redux import (
    CombineReducerRegisterAction,
    CombineReducerUnregisterAction,
    ReducerType,
)

from ubo_app.constants import (
    DEBUG_TASKS,
    DISABLED_SERVICES,
    ENABLED_SERVICES,
    PACKAGE_NAME,
    SERVICES_LOOP_GRACE_PERIOD,
    SERVICES_PATH,
)
from ubo_app.logger import ThreadLevelFilter, logger
from ubo_app.store.settings.types import (
    ServiceState,
    SettingsServiceSetStatusAction,
    SettingsSetServicesAction,
    SettingsStartServiceEvent,
    SettingsStopServiceEvent,
)
from ubo_app.utils.error_handlers import STACKS, loop_exception_handler
from ubo_app.utils.service import ServiceUnavailableError, get_service

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence
    from importlib.machinery import ModuleSpec
    from types import ModuleType

    from redux.basic_types import TaskCreatorCallback
    from ubo_handle import (  # pyright: ignore [reportMissingModuleSource]
        ReducerRegistrar,
        SetupFunction,
        SetupFunctionReturnType,
    )

    from ubo_app.utils.types import Subscriptions


SERVICES_BY_PATH: dict[Path, UboServiceThread] = {}
SERVICE_PATHS_BY_ID: dict[str, Path] = OrderedDict()
ROOT_PATH = Path(__file__).parent


class DisabledServiceError(Exception):
    """Raised when a service is disabled."""


# Customized module finder and module loader for ubo services to avoid mistakenly
# loading conflicting names in different services.
class UboModuleLoader(SourceFileLoader):
    cache: ClassVar[dict[str, weakref.ReferenceType[ModuleType]]] = {}

    @property
    def cache_id(self: UboModuleLoader) -> str:
        return f'{self.path}:{self.name}'

    def create_module(
        self: UboModuleLoader,
        spec: ModuleSpec,
    ) -> ModuleType | None:
        _ = spec
        if (
            self.cache_id in UboModuleLoader.cache
            and UboModuleLoader.cache[self.cache_id]() is not None
        ):
            return UboModuleLoader.cache[self.cache_id]()
        return None

    def exec_module(self: UboModuleLoader, module: ModuleType) -> None:
        if (
            self.cache_id in UboModuleLoader.cache
            and UboModuleLoader.cache[self.cache_id]() is not None
        ):
            return
        super().exec_module(module)
        UboModuleLoader.cache[self.cache_id] = weakref.ref(module)

    def get_filename(self: UboModuleLoader, name: str | None = None) -> str:
        return super().get_filename(name.split(':')[-1] if name else name)


class UboServiceFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self: UboServiceFinder,
        fullname: str,
        _: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if fullname.startswith(PACKAGE_NAME):
            return None

        try:
            service = get_service()
        except ServiceUnavailableError:
            pass
        else:
            if not service.is_alive():
                if service.is_started:
                    msg = 'No import is allowed after the service is finished.'
                    raise ImportError(msg)
                msg = (
                    'No import is allowed in the global scope of `ubo_handle.py` files.'
                )
                raise ImportError(msg)

            module_name = f'{service.service_uid}:{fullname}'

            spec = PathFinder.find_spec(
                fullname,
                [service.path.as_posix()],
                target,
            )
            if spec and spec.origin:
                spec.name = module_name
                spec.loader = UboModuleLoader(fullname, spec.origin)
            return spec

        return None


sys.meta_path.insert(0, UboServiceFinder())


class UboServiceThread(threading.Thread):
    def __init__(
        self: UboServiceThread,
        path: Path,
        *,
        allowed_service_ids: Sequence[str] | None = [],
    ) -> None:
        self.path = path
        self.allowed_service_ids = allowed_service_ids

        super().__init__(name=path.name)
        self.service_uid = self.path.as_posix().replace('.', '_')
        self.label = '<NOT SET>'
        self.should_auto_restart = False
        self.is_enabled = False

        self.module = None
        self.is_started = False
        self.has_reducer = False

        self._reducer_barrier = None
        self.subscriptions: Subscriptions = []

    def set_reducer_barrier(
        self: UboServiceThread,
        reducer_barrier: threading.Barrier,
    ) -> None:
        self._reducer_barrier = reducer_barrier

    def register_reducer(self: UboServiceThread, reducer: ReducerType) -> None:
        if self.has_reducer:
            msg = '`register_reducer` can only be called once per service'
            raise RuntimeError(msg)

        self.has_reducer = True
        from ubo_app.store.main import root_reducer_id, store

        logger.debug(
            'Registering ubo service reducer',
            extra={
                'service_id': self.service_id,
                'label': self.label,
                'reducer': f'{reducer.__module__}.{reducer.__name__}',
            },
        )

        store.dispatch(
            CombineReducerRegisterAction(
                combine_reducers_id=root_reducer_id,
                key=self.service_id,
                reducer=reducer,
            ),
        )

        self._wait_for_reducers()

    def _wait_for_reducers(self: UboServiceThread) -> None:
        if self._reducer_barrier:
            with contextlib.suppress(threading.BrokenBarrierError):
                self._reducer_barrier.wait()

    def register(
        self: UboServiceThread,
        *,
        service_id: str,
        label: str,
        setup: SetupFunction,
        is_enabled: bool = True,
        should_auto_restart: bool = False,
    ) -> None:
        if (
            service_id in DISABLED_SERVICES
            or (ENABLED_SERVICES and service_id not in ENABLED_SERVICES)
            or (self.allowed_service_ids and service_id not in self.allowed_service_ids)
        ):
            logger.debug(
                'Skipping disabled ubo service',
                extra={
                    'service_id': service_id,
                    'label': label,
                    'enabled services': ENABLED_SERVICES,
                    'disabled services': DISABLED_SERVICES,
                    'allowed service ids': self.allowed_service_ids,
                },
            )
            msg = f'Service {service_id} is disabled'
            raise DisabledServiceError(msg)

        self.label = label
        self.service_id = service_id
        self.setup = setup
        self.is_enabled = is_enabled
        self.should_auto_restart = should_auto_restart

        logger.debug(
            'Ubo service registered!',
            extra={
                'service_id': self.service_id,
                'label': self.label,
            },
        )

    def initiate(self: UboServiceThread) -> None:
        try:
            if self.path.exists():
                self.spec = PathFinder.find_spec(
                    'ubo_handle',
                    [self.path.as_posix()],
                    None,
                )
                if not self.spec or not self.spec.origin:
                    return
                self.spec.name = f'{self.service_uid}:ubo_handle'
                self.spec.loader = UboModuleLoader(
                    'ubo_handle',
                    self.spec.origin,
                )
                self.module = importlib.util.module_from_spec(self.spec)

        except Exception:
            logger.exception('Error loading service', extra={'path': self.path})
            return

        if self.module and self.spec and self.spec.loader:
            SERVICES_BY_PATH[self.path] = self
            try:
                cast('UboServiceThread', self.module).register = self.register
                self.spec.loader.exec_module(self.module)
            except DisabledServiceError:
                del SERVICES_BY_PATH[self.path]
            except Exception:
                del SERVICES_BY_PATH[self.path]
                logger.exception('Error loading service', extra={'path': self.path})
            else:
                SERVICE_PATHS_BY_ID[self.service_id] = self.path

    def start(self: UboServiceThread) -> None:
        if not hasattr(self, 'setup'):
            return

        super().start()

    def stop(self: UboServiceThread) -> None:
        self.loop.call_soon_threadsafe(self.loop.create_task, self.shutdown())

    def run(self: UboServiceThread) -> None:
        from ubo_app.store.main import store

        self.loop = asyncio.new_event_loop()
        self.loop.set_exception_handler(loop_exception_handler)

        @store.autorun(
            lambda state: state.settings.services[self.service_id].log_level
            if self.service_id in state.settings.services
            else None,
        )
        def set_log_level(log_level: int | None) -> None:
            ThreadLevelFilter.set_thread_level(self.name, log_level)

        logger.info(
            'Starting service thread',
            extra={
                'thread_native_id': self.native_id,
                'service_label': self.label,
                'service_id': self.service_id,
            },
        )
        asyncio.set_event_loop(self.loop)

        async def setup_wrapper() -> None:
            result = None
            try:
                if len(inspect.signature(self.setup).parameters) == 0:
                    self._wait_for_reducers()
                    result = cast(
                        'Callable[[], SetupFunctionReturnType]',
                        self.setup,
                    )()
                elif len(inspect.signature(self.setup).parameters) == 1:
                    result = cast(
                        'Callable[[ReducerRegistrar], SetupFunctionReturnType]',
                        self.setup,
                    )(self.register_reducer)

                if asyncio.iscoroutine(result):
                    result = await result
            except Exception:
                logger.exception(
                    'Error during setup',
                    extra={
                        'service_id': self.service_id,
                        'label': self.label,
                    },
                )
                raise

            self.is_started = True

            if result:
                self.subscriptions = result

            store.dispatch(
                SettingsServiceSetStatusAction(
                    service_id=self.service_id,
                    is_active=True,
                ),
            )

            del self.setup_task

        self.setup_task = setup_wrapper()
        self.loop.create_task(self.setup_task, name=f'Setup task for {self.label}')

        try:
            self.loop.run_forever()
        except Exception:
            logger.exception(
                'Ubo service thread ran into an error and stopped',
                extra={
                    'thread_native_id': self.native_id,
                    'service_label': self.label,
                    'service_id': self.service_id,
                },
            )
            self.kill()
            raise
        else:
            logger.info(
                'Ubo service thread stopped gracefully',
                extra={
                    'thread_native_id': self.native_id,
                    'service_label': self.label,
                    'service_id': self.service_id,
                },
            )
        finally:
            ThreadLevelFilter.set_thread_level(self.name, None)
            store.dispatch(
                SettingsServiceSetStatusAction(
                    service_id=self.service_id,
                    is_active=False,
                ),
            )

    def __repr__(self: UboServiceThread) -> str:
        return (
            f'<UboServiceThread id='
            f'{self.service_id} label={self.label} name={self.name}>'
        )

    def run_coroutine(
        self: UboServiceThread,
        coroutine: Coroutine,
        callback: TaskCreatorCallback | None = None,
    ) -> asyncio.Handle:
        def task_wrapper(stack: str) -> None:
            task = self.loop.create_task(coroutine)
            if DEBUG_TASKS:
                STACKS[task] = stack
            if callback:
                callback(task)

        return self.loop.call_soon_threadsafe(
            task_wrapper,
            ''.join(traceback.format_stack()[:-3]) if DEBUG_TASKS else '',
        )

    async def shutdown(self: UboServiceThread) -> None:
        from ubo_app.logger import logger

        logger.debug(
            'Shutting down service thread',
            extra={
                'thread_native_id': self.native_id,
                'service_label': self.label,
                'service_id': self.service_id,
            },
        )

        await self._clean_subscriptions()
        await self._clean_remaining_tasks()
        self._unregister_reducer()
        self._cleanup()

    async def _clean_subscriptions(self: UboServiceThread) -> None:
        if not hasattr(self, 'subscriptions'):
            return
        subscriptions = self.subscriptions
        del self.subscriptions
        tasks = []
        for unsubscribe in subscriptions:
            try:
                result = unsubscribe()
                if asyncio.iscoroutine(result):
                    tasks.append(result)
            except Exception:
                logger.exception(
                    'Error during cleanup',
                    extra={
                        'service_id': self.service_id,
                        'label': self.label,
                        'cleanup_callback': unsubscribe,
                    },
                )
        while tasks:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=SERVICES_LOOP_GRACE_PERIOD,
                )
            tasks = [task for task in tasks if not task.done()]
            await asyncio.sleep(0.1)

    async def _clean_remaining_tasks(self: UboServiceThread) -> None:
        if not self.loop.is_running():
            return
        while True:
            tasks = [
                task
                for task in asyncio.all_tasks(self.loop)
                if task is not asyncio.current_task(self.loop)
                and task.cancelling() == 0
                and not task.done()
            ]
            logger.debug(
                'Waiting for tasks to finish',
                extra={
                    'tasks': tasks,
                    'thread_': self,
                    'service_id': self.service_id,
                    'service_label': self.label,
                },
            )
            if not tasks:
                break
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(
                    asyncio.gather(
                        *tasks,
                        return_exceptions=True,
                    ),
                    timeout=SERVICES_LOOP_GRACE_PERIOD,
                )
            await asyncio.sleep(0.1)
        self.loop.stop()

    def _unregister_reducer(self: UboServiceThread) -> None:
        if self.has_reducer:
            from ubo_app.store.main import root_reducer_id, store

            store.dispatch(
                CombineReducerUnregisterAction(
                    combine_reducers_id=root_reducer_id,
                    key=self.service_id,
                ),
            )
            self.has_reducer = False

    def _cleanup(self: UboServiceThread) -> None:
        from ubo_app.utils import bus_provider

        if self in bus_provider.system_buses:
            del bus_provider.system_buses[self]
        if self in bus_provider.user_buses:
            del bus_provider.user_buses[self]

        for name in list(sys.modules):
            if name.startswith(f'{self.service_uid}:'):
                del sys.modules[name]

        for name in list(UboModuleLoader.cache):
            if name.startswith(f'{self.service_uid}:'):
                del UboModuleLoader.cache[name]

        if self.path in SERVICES_BY_PATH:
            del SERVICES_BY_PATH[self.path]

        del self.module

    def kill(self: UboServiceThread) -> None:
        if self.ident is None:
            return
        if self.loop.is_running():
            self.loop.create_task(self.shutdown())
        else:
            asyncio.new_event_loop().run_until_complete(self.shutdown())
        if not self.is_alive():
            return
        tid = ctypes.c_long(self.ident)
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            tid,
            ctypes.py_object(SystemExit),
        )
        if res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
            msg = 'Failed to stop thread'
            raise RuntimeError(msg)


async def start(event: SettingsStartServiceEvent) -> None:
    if event.service_id in SERVICE_PATHS_BY_ID and (
        SERVICE_PATHS_BY_ID[event.service_id] not in SERVICES_BY_PATH
        or not SERVICES_BY_PATH[SERVICE_PATHS_BY_ID[event.service_id]].is_started
    ):
        await asyncio.sleep(event.delay)
        if SERVICE_PATHS_BY_ID[event.service_id] not in SERVICES_BY_PATH:
            service = UboServiceThread(SERVICE_PATHS_BY_ID[event.service_id])
            service.initiate()
        SERVICES_BY_PATH[SERVICE_PATHS_BY_ID[event.service_id]].start()


async def stop(event: SettingsStopServiceEvent) -> None:
    if (
        event.service_id in SERVICE_PATHS_BY_ID
        and SERVICE_PATHS_BY_ID[event.service_id] in SERVICES_BY_PATH
        and SERVICES_BY_PATH[SERVICE_PATHS_BY_ID[event.service_id]].is_alive()
    ):
        service = SERVICES_BY_PATH[SERVICE_PATHS_BY_ID[event.service_id]]
        logger.debug(
            'Stopping service',
            extra={
                'service_id': event.service_id,
                'label': service.label,
            },
        )
        service.stop()
        await asyncio.to_thread(service.join, timeout=3)
        if service.is_alive():
            service.kill()
            await asyncio.to_thread(service.join, timeout=3)

        import gc

        gc.collect()


def _report_successful_reducer_registration(services: list[UboServiceThread]) -> None:
    logger.info(
        'All reducers registered successfully',
        extra={
            'service_ids': [service.service_id for service in services],
        },
    )


def stop_services(
    service_ids: Sequence[str] | None = None,
) -> None:
    for service in list(SERVICES_BY_PATH.values()):
        if service_ids and service.service_id not in service_ids:
            continue
        service.stop()


def load_services(
    service_ids: Sequence[str] | None = None,
    gap_duration: float = 0,
) -> None:
    from ubo_app.store.main import store
    from ubo_app.utils.persistent_store import read_from_persistent_store

    for services_directory_path in [
        ROOT_PATH.joinpath('services').as_posix(),
        *SERVICES_PATH,
    ]:
        directory_path = Path(services_directory_path).absolute()
        if directory_path.is_dir():
            for service_path in sorted(directory_path.iterdir()):
                if not service_path.is_dir() or service_path in SERVICES_BY_PATH.copy():
                    continue
                service = UboServiceThread(
                    service_path.absolute(),
                    allowed_service_ids=service_ids,
                )
                service.initiate()

    store.subscribe_event(SettingsStartServiceEvent, start)
    store.subscribe_event(SettingsStopServiceEvent, stop)

    services = {
        service.service_id: ServiceState(
            id=service.service_id,
            label=service.label,
            is_active=service.is_alive(),
            is_enabled=service.is_enabled,
            log_level=logging.INFO,
            should_auto_restart=service.should_auto_restart,
        )
        for service in SERVICES_BY_PATH.values()
    }

    for service in read_from_persistent_store(
        'services',
        default={},
    ):
        if service['id'] in SERVICE_PATHS_BY_ID:
            services[service['id']] = replace(
                services[service['id']],
                is_enabled=service.get(
                    'is_enabled',
                    services[service['id']].is_enabled,
                ),
                log_level=service.get('log_level', logging.INFO),
                should_auto_restart=service.get(
                    'should_auto_restart',
                    services[service['id']].should_auto_restart,
                ),
            )

    to_run_services = [
        service
        for service in SERVICES_BY_PATH.values()
        if service.is_enabled and (not service_ids or service.service_id in service_ids)
    ]

    reducer_barrier = threading.Barrier(
        len(to_run_services),
        action=lambda: _report_successful_reducer_registration(to_run_services),
        timeout=10,
    )

    for service in to_run_services:
        service.set_reducer_barrier(reducer_barrier)

    store.dispatch(
        SettingsSetServicesAction(services=services, gap_duration=gap_duration),
    )
