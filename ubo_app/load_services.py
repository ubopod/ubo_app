# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.abc
import importlib.util
import inspect
import os
import sys
import threading
import time
import traceback
import uuid
import weakref
from collections.abc import Callable, Coroutine, Sequence
from importlib.machinery import PathFinder, SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from redux import CombineReducerRegisterAction, ReducerType

from ubo_app.constants import (
    DEBUG_MODE_TASKS,
    DISABLED_SERVICES,
    ENABLED_SERVICES,
    SERVICES_LOOP_GRACE_PERIOD,
    SERVICES_PATH,
)
from ubo_app.error_handlers import STACKS, loop_exception_handler
from ubo_app.logging import logger

if TYPE_CHECKING:
    from asyncio.tasks import Task
    from importlib.machinery import ModuleSpec
    from types import ModuleType

    from ubo_handle import SetupFunction  # pyright: ignore [reportMissingModuleSource]

ROOT_PATH = Path(__file__).parent
REGISTERED_PATHS: dict[Path, UboServiceThread] = {}
WHITE_LIST = [*ENABLED_SERVICES]


# Customized module finder and module loader for ubo services to avoid mistakenly
# loading conflicting names in different services.
# This is a temporary hack until each service runs in its own process.
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
        cast(Any, module).name = self.service.name
        cast(Any, module).service_uid = self.service.service_uid
        cast(Any, module).label = self.service.label
        cast(Any, module).service_id = self.service.service_id
        cast(Any, module).path = self.service.path
        cast(Any, module)._create_task = (  # noqa: SLF001
            lambda task, callback=None: self.service.run_task(
                task,
                callback,
            )
        )

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
                msg = (
                    'No import other than `ubo_app.services` is allowed in the global'
                    ' scope of `ubo_handle.py` files.'
                )
                raise RuntimeError(msg)

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

        self.path = path

        self.module = None

    def register_reducer(self: UboServiceThread, reducer: ReducerType) -> None:
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

        logger.debug(
            'Ubo service registered!',
            extra={
                'service_id': self.service_id,
                'label': self.label,
            },
        )

        from redux import FinishEvent

        from ubo_app.store.main import store

        def stop() -> None:
            unsubscribe()
            self.stop()

        unsubscribe = store.subscribe_event(FinishEvent, stop)

        self.start()

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
            try:
                REGISTERED_PATHS[self.path] = self
                cast(UboServiceThread, self.module).register = self.register
                self.spec.loader.exec_module(self.module)
            except Exception:
                del REGISTERED_PATHS[self.path]
                logger.exception('Error loading service', extra={'path': self.path})

    def run(self: UboServiceThread) -> None:
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

        result = None
        if len(inspect.signature(self.setup).parameters) == 0:
            result = cast(Callable[[], None], self.setup)()
        elif len(inspect.signature(self.setup).parameters) == 1:
            result = cast(Callable[[UboServiceThread], None], self.setup)(self)

        if asyncio.iscoroutine(result):
            self.loop.create_task(result, name=f'Setup task for {self.label}')

        self.loop.run_forever()

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
        from ubo_app.logging import logger

        logger.debug(
            'Stopping service thread',
            extra={
                'thread_native_id': self.native_id,
                'service_label': self.label,
                'service_id': self.service_id,
            },
        )

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

    def stop(self: UboServiceThread) -> None:
        self.loop.call_soon_threadsafe(self.loop.create_task, self.shutdown())


def load_services(service_ids: Sequence[str] | None = None, delay: float = 0) -> None:
    WHITE_LIST.extend(service_ids or [])

    services: list[UboServiceThread] = []
    for services_directory_path in [
        ROOT_PATH.joinpath('services').as_posix(),
        *SERVICES_PATH,
    ]:
        directory_path = Path(services_directory_path).absolute()
        if directory_path.is_dir():
            for service_path in sorted(directory_path.iterdir()):
                if not service_path.is_dir() or service_path in REGISTERED_PATHS.copy():
                    continue
                current_path = Path().absolute()
                os.chdir(service_path.as_posix())

                services.append(UboServiceThread(service_path))

                os.chdir(current_path)

    for service in services:
        service.initiate()
        if delay:
            time.sleep(delay)
