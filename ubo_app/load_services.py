# ruff: noqa: D100, D101, D102, D103, D104, D105, D107
from __future__ import annotations

import asyncio
import importlib
import importlib.abc
import importlib.util
import os
import sys
import threading
import traceback
import uuid
from importlib.machinery import PathFinder, SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence, cast

from redux import (
    CombineReducerRegisterAction,
    FinishEvent,
    ReducerType,
)

from ubo_app.constants import DEBUG_MODE, SERVICES_PATH
from ubo_app.logging import logger

if TYPE_CHECKING:
    from importlib.machinery import ModuleSpec
    from types import ModuleType

ROOT_PATH = Path(__file__).parent
REGISTERED_PATHS: dict[Path, UboServiceThread] = {}


# Customized module finder and module loader for ubo services to avoid mistakenly
# loading conflicting names in different services.
# This is a temporary hack until each service runs in its own process.
class UboServiceModuleLoader(SourceFileLoader):
    def get_filename(self: UboServiceModuleLoader, name: str | None = None) -> str:
        return super().get_filename(name.split(':')[1] if name else name)

    def create_module(
        self: UboServiceModuleLoader,
        spec: ModuleSpec,
    ) -> ModuleType | None:
        if spec.name in sys.modules:
            return sys.modules[spec.name]
        return super().create_module(spec)


class UboServiceLoopLoader(importlib.abc.Loader):
    def __init__(self: UboServiceLoopLoader, thread: UboServiceThread) -> None:
        self.thread = thread

    def exec_module(self: UboServiceLoopLoader, module: ModuleType) -> None:
        cast(Any, module).create_task = (
            lambda *args: self.thread.loop.call_soon_threadsafe(
                lambda: self.thread.loop.create_task(*args),
            )
        )

    def __repr__(self: UboServiceLoopLoader) -> str:
        return f'{self.thread.path}'


class UboServiceFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self: UboServiceFinder,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if path is None:
            stack = traceback.extract_stack()
            matching_path = next(
                (
                    registered_path
                    for stack_path in stack[::-1]
                    for registered_path in REGISTERED_PATHS
                    if stack_path.filename.startswith(registered_path.as_posix())
                ),
                None,
            )
            if matching_path:
                thread = REGISTERED_PATHS[matching_path]
                module_name = f'{thread.service_id}:{fullname}'

                if fullname == '_loop':
                    return importlib.util.spec_from_loader(
                        module_name,
                        UboServiceLoopLoader(thread),
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
        service_id: str,
    ) -> None:
        super().__init__()
        self.service_id = service_id
        self.path = path
        self.loop = asyncio.new_event_loop()
        if DEBUG_MODE:
            self.loop.set_debug(enabled=True)
        try:
            if path.exists():
                module_name = f'{service_id}:ubo_handle'
                PathFinder.find_spec(
                    module_name,
                    [path.as_posix()],
                    None,
                )
                self.spec = PathFinder.find_spec(
                    'ubo_handle',
                    [path.as_posix()],
                    None,
                )
                if not self.spec:
                    return
                self.spec.__module__ = module_name
                module = importlib.util.module_from_spec(self.spec)
                sys.modules[module_name] = module
                self.module = module

        except Exception as exception:  # noqa: BLE001
            logger.error(f'Error loading "{path}"')
            logger.exception(exception)

    def run(self: UboServiceThread) -> None:
        from ubo_app import store

        asyncio.set_event_loop(self.loop)
        if self.module and self.spec and self.spec.loader:
            self.spec.loader.exec_module(self.module)

        store.subscribe_event(FinishEvent, lambda _: self.stop())
        self.loop.run_forever()

    def stop(self: UboServiceThread) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


def register_service(
    service_id: str,
    label: str,
    reducer: ReducerType | None = None,
) -> None:
    from ubo_app import store

    logger.info(
        'Registering ubo serivce',
        extra={
            'service_id': service_id,
            'label': label,
            'has_reducer': reducer is not None,
        },
    )

    if reducer is not None:
        store.dispatch(
            CombineReducerRegisterAction(
                _id=store.root_reducer_id,
                key=service_id,
                reducer=reducer,
            ),
        )


def load_services() -> None:
    for services_directory_path in [
        ROOT_PATH.joinpath('services').as_posix(),
        *SERVICES_PATH,
    ]:
        if Path(services_directory_path).is_dir():
            for service_path in Path(services_directory_path).iterdir():
                service_id = uuid.uuid4().hex
                if not service_path.is_dir():
                    continue
                current_path = os.curdir
                os.chdir(service_path.as_posix())

                thread = UboServiceThread(
                    service_path,
                    service_id,
                )
                REGISTERED_PATHS[service_path] = thread
                thread.start()

                os.chdir(current_path)
