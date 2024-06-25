# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import base64
import functools
import sys
from asyncio import Handle
from datetime import datetime
from pathlib import Path
from threading import current_thread, main_thread
from types import GenericAlias
from typing import TYPE_CHECKING, Any, TypeVar, cast, get_origin, overload

import dill
from immutable import Immutable
from redux import (
    BaseCombineReducerState,
    BaseEvent,
    CombineReducerAction,
    CreateStoreOptions,
    FinishAction,
    InitAction,
    Store,
    combine_reducers,
)

from ubo_app.constants import DEBUG_MODE, STORE_GRACE_PERIOD
from ubo_app.logging import logger
from ubo_app.store.core import MainAction, MainEvent, MainState
from ubo_app.store.core.reducer import reducer as main_reducer
from ubo_app.store.services.camera import CameraAction, CameraEvent, CameraState
from ubo_app.store.services.docker import DockerAction, DockerState
from ubo_app.store.services.ip import IpAction, IpEvent, IpState
from ubo_app.store.services.keypad import KeypadAction, KeypadEvent
from ubo_app.store.services.lightdm import LightDMAction, LightDMState
from ubo_app.store.services.notifications import (
    NotificationsAction,
    NotificationsEvent,
    NotificationsState,
)
from ubo_app.store.services.rgb_ring import RgbRingAction, RgbRingState
from ubo_app.store.services.sensors import SensorsAction, SensorsState
from ubo_app.store.services.sound import SoundAction, SoundState
from ubo_app.store.services.ssh import SSHAction, SSHState
from ubo_app.store.services.voice import VoiceAction, VoiceState
from ubo_app.store.services.vscode import VSCodeAction, VSCodeState
from ubo_app.store.services.wifi import WiFiAction, WiFiEvent, WiFiState
from ubo_app.store.status_icons import StatusIconsAction, StatusIconsState
from ubo_app.store.status_icons.reducer import reducer as status_icons_reducer
from ubo_app.store.update_manager import UpdateManagerAction, UpdateManagerState
from ubo_app.store.update_manager.reducer import reducer as update_manager_reducer
from ubo_app.utils.fake import Fake
from ubo_app.utils.serializer import add_type_field

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from redux.basic_types import SnapshotAtom, TaskCreatorCallback

if current_thread() is not main_thread():
    msg = 'Store should be created in the main thread'
    raise RuntimeError(msg)

triggers = []


def scheduler(callback: Callable[[], None], *, interval: bool) -> None:
    from kivy.clock import Clock

    trigger = Clock.create_trigger(lambda _: callback(), 0, interval=interval)
    trigger()
    triggers.append(trigger)


class RootState(BaseCombineReducerState):
    main: MainState
    camera: CameraState
    rgb_ring: RgbRingState
    lightdm: LightDMState
    status_icons: StatusIconsState
    update_manager: UpdateManagerState
    sensors: SensorsState
    ssh: SSHState
    sound: SoundState
    wifi: WiFiState
    ip: IpState
    notifications: NotificationsState
    docker: DockerState
    voice: VoiceState
    vscode: VSCodeState


class ScreenshotEvent(BaseEvent): ...


class SnapshotEvent(BaseEvent): ...


ActionType = (
    CombineReducerAction
    | StatusIconsAction
    | UpdateManagerAction
    | MainAction
    | InitAction
    | FinishAction
    | StatusIconsAction
    | KeypadAction
    | MainAction
    | LightDMAction
    | SensorsAction
    | SSHAction
    | SoundAction
    | CameraAction
    | WiFiAction
    | IpAction
    | NotificationsAction
    | DockerAction
    | RgbRingAction
    | VoiceAction
    | VSCodeAction
)
EventType = (
    MainEvent
    | KeypadEvent
    | CameraEvent
    | WiFiEvent
    | IpEvent
    | ScreenshotEvent
    | SnapshotEvent
    | NotificationsEvent
)

root_reducer, root_reducer_id = combine_reducers(
    state_type=RootState,
    action_type=ActionType,  # pyright: ignore [reportArgumentType]
    event_type=EventType,  # pyright: ignore [reportArgumentType]
    main=main_reducer,
    status_icons=status_icons_reducer,
    update_manager=update_manager_reducer,
)

T = TypeVar('T')
LoadedObject = int | float | str | bool | None | Immutable | list['LoadedObject']


class UboStore(Store[RootState, ActionType, EventType]):
    @classmethod
    def serialize_value(cls: type[UboStore], obj: object | type) -> SnapshotAtom:
        from redux.autorun import Autorun
        from ubo_gui.page import PageWidget

        if isinstance(obj, Autorun):
            obj = obj()
        if isinstance(obj, type) and issubclass(obj, PageWidget):
            import ubo_app

            _ = ubo_app
            file_path = sys.modules[obj.__module__].__file__
            ubo_app_path = sys.modules['ubo_app'].__file__
            if file_path and ubo_app_path:
                root_path = Path(ubo_app_path).parent
                return f"""{Path(file_path).relative_to(root_path).as_posix()}:{
                obj.__name__}"""
            return f'{obj.__module__}:{obj.__name__}'
        if isinstance(obj, functools.partial):
            return f'<functools.partial:{cls.serialize_value(obj.func)}>'
        if callable(obj):
            return f'<function:{obj.__name__}>'
        if isinstance(obj, dict):
            return {k: cls.serialize_value(v) for k, v in obj.items()}
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Handle | Fake | PageWidget):
            return f'<{type(obj).__name__}>'
        return super().serialize_value(obj)

    @classmethod
    def _serialize_dataclass_to_dict(
        cls: type[UboStore],
        obj: Immutable,
    ) -> dict[str, Any]:
        result = super()._serialize_dataclass_to_dict(obj)
        return add_type_field(obj, result)

    @overload
    def load_object(
        self: UboStore,
        data: SnapshotAtom,
    ) -> int | float | str | bool | None | Immutable: ...
    @overload
    def load_object(
        self: UboStore,
        data: SnapshotAtom,
        *,
        object_type: type[T],
    ) -> T: ...

    def load_object(
        self: UboStore,
        data: Any,
        *,
        object_type: type[T] | None = None,
    ) -> LoadedObject | T:
        if isinstance(data, int | float | str | bool | None):
            return data
        if isinstance(data, list):
            return [self.load_object(i) for i in data]
        if (
            isinstance(data, dict)
            and '_type' in data
            and isinstance(type_ := data.pop('_type'), str)
        ):
            class_ = dill.loads(base64.b64decode(type_.encode('utf-8')))  # noqa: S301
            parameters = {key: self.load_object(value) for key, value in data.items()}

            return class_(**parameters)
        if not object_type or isinstance(
            data,
            get_origin(object_type)  # pyright: ignore [reportArgumentType]
            if isinstance(object_type, GenericAlias)
            else object_type,
        ):
            return cast(T, data)

        msg = f'Invalid data type {type(data)}'
        raise TypeError(msg)


def create_task(
    coro: Coroutine,
    *,
    callback: TaskCreatorCallback | None = None,
) -> None:
    from ubo_app.utils.async_ import create_task

    create_task(coro, callback)


def stop_app() -> None:
    from kivy.app import App
    from kivy.clock import mainthread

    for trigger in triggers:
        trigger.cancel()

    if App.get_running_app():
        mainthread(App.get_running_app().stop)()


def action_middleware(action: ActionType) -> ActionType:
    logger.debug(
        'Action dispatched',
        extra={'action': action},
    )
    return action


def event_middleware(event: EventType) -> EventType:
    logger.debug(
        'Event dispatched',
        extra={'event': event},
    )
    return event


store = UboStore(
    root_reducer,
    CreateStoreOptions(
        auto_init=False,
        scheduler=scheduler,
        action_middlewares=[action_middleware],
        event_middlewares=[event_middleware],
        task_creator=create_task,
        on_finish=stop_app,
        grace_time_in_seconds=STORE_GRACE_PERIOD,
    ),
)

autorun = store.autorun
dispatch = store.dispatch
subscribe = store.subscribe
subscribe_event = store.subscribe_event
view = store.view

dispatch(InitAction())

if DEBUG_MODE:
    subscribe(
        lambda state: logger.verbose('State updated', extra={'state': state}),
    )

__all__ = ('autorun', 'dispatch', 'subscribe', 'subscribe_event')
