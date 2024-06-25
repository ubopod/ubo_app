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
import traceback
import uuid
from collections.abc import Callable, Sequence
from importlib.machinery import PathFinder, SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from redux import CombineReducerRegisterAction, ReducerType

from ubo_app.constants import (
    DEBUG_MODE,
    DISABLED_SERVICES,
    SERVICES_LOOP_GRACE_PERIOD,
    SERVICES_PATH,
)
from ubo_app.error_handlers import loop_exception_handler
from ubo_app.logging import logger

if TYPE_CHECKING:
    from importlib.machinery import ModuleSpec
    from types import ModuleType

    from ubo_app.services import SetupFunction

ROOT_PATH = Path(__file__).parent
REGISTERED_PATHS: dict[Path, UboServiceThread] = {}
WHITE_LIST = []


# Customized module finder and module loader for ubo services to avoid mistakenly
# loading conflicting names in different services.
# This is a temporary hack until each service runs in its own process.
class UboServiceModuleLoader(SourceFileLoader):
    cache: ClassVar[dict[str, ModuleType]] = {}

    @property
    def cache_id(self: UboServiceModuleLoader) -> str:
        return f'{self.path}:{self.name}'

    def create_module(
        self: UboServiceModuleLoader,
        spec: ModuleSpec,
    ) -> ModuleType | None:
        _ = spec
        if self.cache_id in UboServiceModuleLoader.cache:
            return UboServiceModuleLoader.cache[self.cache_id]
        return None

    def exec_module(self: UboServiceModuleLoader, module: ModuleType) -> None:
        if self.cache_id in UboServiceModuleLoader.cache:
            return
        super().exec_module(module)
        UboServiceModuleLoader.cache[self.cache_id] = module

    def get_filename(self: UboServiceModuleLoader, name: str | None = None) -> str:
        return super().get_filename(name.split(':')[-1] if name else name)


class UboServiceLoopLoader(importlib.abc.Loader):
    def __init__(self: UboServiceLoopLoader, service: UboServiceThread) -> None:
        self.service = service

    def exec_module(self: UboServiceLoopLoader, module: ModuleType) -> None:
        cast(Any, module)._create_task = (  # noqa: SLF001
            lambda task: self.service.loop.call_soon_threadsafe(
                self.service.loop.create_task,
                task,
            )
        )

    def __repr__(self: UboServiceLoopLoader) -> str:
        return f'{self.service.path}:LoopLoader'


class UboServiceFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self: UboServiceFinder,
        fullname: str,
        _: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        stack = traceback.extract_stack()
        matching_path = next(
            (
                registered_path
                for frame in stack[-2::-1]
                for registered_path in (*REGISTERED_PATHS.keys(), Path('/'))
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

            if fullname == 'ubo_app.utils.loop':
                return importlib.util.spec_from_loader(
                    module_name,
                    UboServiceLoopLoader(service),
                )

            spec = PathFinder.find_spec(
                fullname,
                [matching_path.as_posix()],
                target,
            )
            if spec and spec.origin:
                spec.name = module_name
                spec.loader = UboServiceModuleLoader(fullname, spec.origin)
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
        from ubo_app.store.main import dispatch, root_reducer_id

        logger.debug(
            'Registering ubo service reducer',
            extra={
                'service_id': self.service_id,
                'label': self.label,
                'reducer': f'{reducer.__module__}.{reducer.__name__}',
            },
        )

        dispatch(
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
            logger.info(
                'Skipping disabled ubo service',
                extra={
                    'service_id': service_id,
                    'label': label,
                    'disabled_services': DISABLED_SERVICES,
                },
            )
            return

        if WHITE_LIST and service_id not in WHITE_LIST:
            logger.info(
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
                self.spec.loader = UboServiceModuleLoader(
                    'ubo_handle',
                    self.spec.origin,
                )
                self.module = importlib.util.module_from_spec(self.spec)

        except Exception:
            logger.exception('Error loading service', extra={'path': self.path})
            return

        if self.module and self.spec and self.spec.loader:
            try:
                cast(UboServiceThread, self.module).register = self.register
                self.spec.loader.exec_module(self.module)
            except Exception:
                logger.exception('Error loading service', extra={'path': self.path})

    def run(self: UboServiceThread) -> None:
        self.loop = asyncio.new_event_loop()
        self.loop.set_exception_handler(loop_exception_handler)
        logger.debug(
            'Starting service thread',
            extra={
                'thread_native_id': self.native_id,
                'service_label': self.label,
                'service_id': self.service_id,
            },
        )
        asyncio.set_event_loop(self.loop)
        if DEBUG_MODE:
            self.loop.set_debug(enabled=True)

        REGISTERED_PATHS[self.path] = self
        result = None
        if len(inspect.signature(self.setup).parameters) == 0:
            result = cast(Callable[[], None], self.setup)()
        elif len(inspect.signature(self.setup).parameters) == 1:
            result = cast(Callable[[UboServiceThread], None], self.setup)(self)

        if asyncio.iscoroutine(result):
            self.loop.create_task(result, name=f'Setup task for {self.label}')

        from redux import FinishEvent

        from ubo_app.store.main import store

        store.subscribe_event(FinishEvent, self.stop)
        self.loop.run_forever()

    def __repr__(self: UboServiceThread) -> str:
        return (
            f'<UboServiceThread id='
            f'{self.service_id} label={self.label} name={self.name}>'
        )

    async def shutdown(self: UboServiceThread) -> None:
        from ubo_app.logging import logger

        logger.debug(
            'Shutting down service thread',
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
            for task in tasks:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(task, timeout=SERVICES_LOOP_GRACE_PERIOD)

        logger.debug('Stopping event loop', extra={'thread_': self})
        self.loop.stop()

    def stop(self: UboServiceThread) -> None:
        self.loop.call_soon_threadsafe(self.loop.create_task, self.shutdown())


def load_services(service_ids: Sequence[str] | None = None) -> None:
    WHITE_LIST.extend(service_ids or [])
    import time

    services = []
    for services_directory_path in [
        ROOT_PATH.joinpath('services').as_posix(),
        *SERVICES_PATH,
    ]:
        if Path(services_directory_path).is_dir():
            for service_path in Path(services_directory_path).iterdir():
                if not service_path.is_dir() or service_path in REGISTERED_PATHS:
                    continue
                current_path = Path().absolute()
                os.chdir(service_path.as_posix())

                services.append(UboServiceThread(service_path))

                os.chdir(current_path)

    for service in services:
        service.initiate()
        time.sleep(0.02)
