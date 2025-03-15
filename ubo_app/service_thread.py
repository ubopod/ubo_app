# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import asyncio
import contextlib
import ctypes
import importlib
import importlib.abc
import importlib.util
import inspect
import sys
import threading
import traceback
import uuid
import weakref
from collections import OrderedDict
from dataclasses import replace
from importlib.machinery import PathFinder, SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from redux import (
    CombineReducerRegisterAction,
    CombineReducerUnregisterAction,
    ReducerType,
)

from ubo_app.constants import (
    DEBUG_MODE_TASKS,
    DISABLED_SERVICES,
    ENABLED_SERVICES,
    SERVICES_LOOP_GRACE_PERIOD,
    SERVICES_PATH,
)
from ubo_app.error_handlers import STACKS, loop_exception_handler
from ubo_app.logger import logger
from ubo_app.store.settings.types import (
    ServiceState,
    SettingsServiceSetStatusAction,
    SettingsSetServicesAction,
    SettingsStartServiceEvent,
    SettingsStopServiceEvent,
)

if TYPE_CHECKING:
    from asyncio.tasks import Task
    from collections.abc import Callable, Coroutine, Sequence
    from importlib.machinery import ModuleSpec
    from types import ModuleType

    from ubo_handle import (  # pyright: ignore [reportMissingModuleSource]
        SetupFunction,
        SetupFunctionReturnType,
    )

REGISTERED_PATHS: dict[Path, UboServiceThread] = {}
SERVICES_BY_ID: dict[str, UboServiceThread] = OrderedDict()
WHITE_LIST = [*ENABLED_SERVICES]
ROOT_PATH = Path(__file__).parent


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


class UboServiceLoader(importlib.abc.Loader):
    def __init__(self: UboServiceLoader, service: UboServiceThread) -> None:
        self.service = service

    def exec_module(self: UboServiceLoader, module: ModuleType) -> None:
        cast('Any', module).name = self.service.name
        cast('Any', module).service_uid = self.service.service_uid
        cast('Any', module).label = self.service.label
        cast('Any', module).service_id = self.service.service_id
        cast('Any', module).path = self.service.path
        cast('Any', module).run_task = self.service.run_task

    def __repr__(self: UboServiceLoader) -> str:
        return f'{self.service.path}:ServiceLoader'


class UboServiceFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self: UboServiceFinder,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        stack = traceback.extract_stack()
        matching_path = next(
            (
                registered_path
                for frame in stack[-2::-1]
                for registered_path in REGISTERED_PATHS.copy()
                if frame.filename.startswith(registered_path.as_posix())
            ),
            None,
        )

        if matching_path in REGISTERED_PATHS:
            service = REGISTERED_PATHS[matching_path]
            module_name = f'{service.service_uid}:{fullname}'

            if not service.is_alive():
                if service.is_started:
                    msg = 'No import is allowed after the service is finished.'
                    raise ImportError(msg)
                msg = (
                    'No import is allowed in the global scope of `ubo_handle.py` files.'
                )
                raise ImportError(msg)

            if fullname == 'ubo_app.service':
                return importlib.util.spec_from_loader(
                    module_name,
                    UboServiceLoader(service),
                )

            spec = PathFinder.find_spec(
                fullname,
                [matching_path.as_posix()],
                target,
            )
            if spec and spec.origin:
                spec.name = module_name
                spec.loader = UboModuleLoader(fullname, spec.origin)
            return spec

        if fullname == 'ubo_app.service':
            module_name = f'_:{fullname}'
            spec = PathFinder.find_spec(
                fullname,
                path,
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
    ) -> None:
        super().__init__()
        self.name = path.name
        self.service_uid = f'{uuid.uuid4().hex}:{self.name}'
        self.label = '<NOT SET>'
        self.service_id = ''
        self.should_auto_restart = False
        self.is_enabled = False

        self.path = path

        self.module = None
        self.is_started = False
        self.has_reducer = False

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
                _id=root_reducer_id,
                key=self.service_id,
                reducer=reducer,
            ),
        )

    def register(
        self: UboServiceThread,
        *,
        service_id: str,
        label: str,
        setup: SetupFunction,
        is_enabled: bool = True,
        should_auto_restart: bool = False,
    ) -> None:
        if service_id in DISABLED_SERVICES:
            logger.debug(
                'Skipping disabled ubo service',
                extra={
                    'service_id': service_id,
                    'label': label,
                    'disabled_services': DISABLED_SERVICES,
                },
            )
            return

        if WHITE_LIST and service_id not in WHITE_LIST:
            logger.debug(
                'Service is not in services white list',
                extra={
                    'service_id': service_id,
                    'label': label,
                    'white_list': WHITE_LIST,
                },
            )
            return

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
                module_name = f'{self.service_uid}:ubo_handle'
                self.spec = PathFinder.find_spec(
                    'ubo_handle',
                    [self.path.as_posix()],
                    None,
                )
                if not self.spec or not self.spec.origin:
                    return
                self.spec.name = module_name
                self.spec.loader = UboModuleLoader(
                    'ubo_handle',
                    self.spec.origin,
                )
                self.module = importlib.util.module_from_spec(self.spec)

        except Exception:
            logger.exception('Error loading service', extra={'path': self.path})
            return

        if self.module and self.spec and self.spec.loader:
            REGISTERED_PATHS[self.path] = self
            try:
                cast('UboServiceThread', self.module).register = self.register
                self.spec.loader.exec_module(self.module)
            except Exception:
                del REGISTERED_PATHS[self.path]
                logger.exception('Error loading service', extra={'path': self.path})

    def start(self: UboServiceThread) -> None:
        if not hasattr(self, 'setup'):
            return

        super().start()

    def stop(self: UboServiceThread) -> None:
        self.loop.call_soon_threadsafe(self.loop.create_task, self.shutdown())

    def run(self: UboServiceThread) -> None:
        from redux import FinishEvent

        from ubo_app.store.main import store

        self.subscriptions = [
            store.subscribe_event(FinishEvent, self.stop),
        ]

        self.loop = asyncio.new_event_loop()
        self.loop.set_exception_handler(loop_exception_handler)

        logger.info(
            'Starting service thread',
            extra={
                'thread_native_id': self.native_id,
                'service_label': self.label,
                'service_id': self.service_id,
            },
        )
        asyncio.set_event_loop(self.loop)

        from ubo_app.store.main import store

        async def setup_wrapper() -> None:
            result = None
            try:
                if len(inspect.signature(self.setup).parameters) == 0:
                    result = cast(
                        'Callable[[], SetupFunctionReturnType]',
                        self.setup,
                    )()
                elif len(inspect.signature(self.setup).parameters) == 1:
                    result = cast(
                        'Callable[[UboServiceThread], SetupFunctionReturnType]',
                        self.setup,
                    )(self)

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
                self.subscriptions += list(result)

            store.dispatch(
                SettingsServiceSetStatusAction(
                    service_id=self.service_id,
                    is_active=True,
                ),
            )

        self.loop.create_task(setup_wrapper(), name=f'Setup task for {self.label}')

        self.loop.run_forever()

        store.dispatch(
            SettingsServiceSetStatusAction(
                service_id=self.service_id,
                is_active=False,
            ),
        )

        logger.info(
            'Ubo service thread stopped',
            extra={
                'thread_native_id': self.native_id,
                'service_label': self.label,
                'service_id': self.service_id,
            },
        )

    def __repr__(self: UboServiceThread) -> str:
        return (
            f'<UboServiceThread id='
            f'{self.service_id} label={self.label} name={self.name}>'
        )

    def run_task(
        self: UboServiceThread,
        coroutine: Coroutine,
        callback: Callable[[Task], None] | None = None,
    ) -> asyncio.Handle:
        def task_wrapper(stack: str) -> None:
            task = self.loop.create_task(coroutine)
            if DEBUG_MODE_TASKS:
                STACKS[task] = stack
            if callback:
                callback(task)

        return self.loop.call_soon_threadsafe(
            task_wrapper,
            ''.join(traceback.format_stack()[:-3]) if DEBUG_MODE_TASKS else '',
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

        await self._cleanup_1()
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

        self._cleanup_2()

        self.loop.stop()

    async def _cleanup_1(self: UboServiceThread) -> None:
        subscriptions = [*self.subscriptions]
        self.subscriptions.clear()
        for unsubscribe in subscriptions:
            try:
                result = unsubscribe()
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=SERVICES_LOOP_GRACE_PERIOD)
            except Exception:
                logger.exception(
                    'Error during cleanup',
                    extra={
                        'service_id': self.service_id,
                        'label': self.label,
                        'cleanup_callback': unsubscribe,
                    },
                )

        if self.has_reducer:
            from ubo_app.store.main import root_reducer_id, store

            store.dispatch(
                CombineReducerUnregisterAction(
                    _id=root_reducer_id,
                    key=self.service_id,
                ),
            )
            self.has_reducer = False

    def _cleanup_2(self: UboServiceThread) -> None:
        from ubo_app.utils import bus_provider

        if self in bus_provider.system_buses:
            del bus_provider.system_buses[self]
        if self in bus_provider.user_buses:
            del bus_provider.user_buses[self]

        for name in list(sys.modules):
            if name.startswith(f'{self.service_uid}:'):
                del sys.modules[name]

        if self.path in REGISTERED_PATHS:
            del REGISTERED_PATHS[self.path]

    def kill(self: UboServiceThread) -> None:
        if not self.is_alive() or self.ident is None:
            return
        self.run_task(self._cleanup_1())
        self._cleanup_2()
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
    if (
        event.service_id in SERVICES_BY_ID
        and not SERVICES_BY_ID[event.service_id].is_started
        and (not WHITE_LIST or event.service_id in WHITE_LIST)
    ):
        await asyncio.sleep(event.delay)
        SERVICES_BY_ID[event.service_id].start()


async def stop(event: SettingsStopServiceEvent) -> None:
    if (
        event.service_id in SERVICES_BY_ID
        and SERVICES_BY_ID[event.service_id].is_alive()
    ):
        logger.debug(
            'Stopping service',
            extra={
                'service_id': event.service_id,
                'label': SERVICES_BY_ID[event.service_id].label,
            },
        )
        path = SERVICES_BY_ID[event.service_id].path
        SERVICES_BY_ID[event.service_id].stop()
        await asyncio.to_thread(SERVICES_BY_ID[event.service_id].join, timeout=3)
        if SERVICES_BY_ID[event.service_id].is_alive():
            logger.warning(
                'Service thread did not stop gracefully, killing it',
                extra={
                    'service_id': event.service_id,
                    'label': SERVICES_BY_ID[event.service_id].label,
                },
            )
            SERVICES_BY_ID[event.service_id].kill()
            await asyncio.to_thread(SERVICES_BY_ID[event.service_id].join, timeout=3)
        del SERVICES_BY_ID[event.service_id]

        import gc

        gc.collect()

        service = UboServiceThread(path)
        service.initiate()
        SERVICES_BY_ID[service.service_id] = service


def clear() -> None:
    SERVICES_BY_ID.clear()


def load_services(
    service_ids: Sequence[str] | None = None,
    gap_duration: float = 0,
) -> None:
    from redux import FinishEvent

    from ubo_app.store.main import store
    from ubo_app.utils.persistent_store import read_from_persistent_store

    WHITE_LIST.extend(service_ids or [])

    for services_directory_path in [
        ROOT_PATH.joinpath('services').as_posix(),
        *SERVICES_PATH,
    ]:
        directory_path = Path(services_directory_path).absolute()
        if directory_path.is_dir():
            for service_path in sorted(directory_path.iterdir()):
                if not service_path.is_dir() or service_path in REGISTERED_PATHS.copy():
                    continue
                service = UboServiceThread(service_path.absolute())
                service.initiate()
                SERVICES_BY_ID[service.service_id] = service

    store.subscribe_event(SettingsStartServiceEvent, start)
    store.subscribe_event(SettingsStopServiceEvent, stop)
    store.subscribe_event(FinishEvent, clear)

    services = {
        service.service_id: ServiceState(
            id=service.service_id,
            label=service.label,
            is_active=service.is_alive(),
            is_enabled=service.is_enabled,
        )
        for service in SERVICES_BY_ID.values()
    }

    for service in read_from_persistent_store(
        'services',
        default={},
    ):
        if service['id'] in SERVICES_BY_ID:
            services[service['id']] = replace(
                services[service['id']],
                is_enabled=service.get(
                    'is_enabled',
                    services[service['id']].is_enabled,
                ),
            )

    store.dispatch(
        SettingsSetServicesAction(services=services, gap_duration=gap_duration),
    )
