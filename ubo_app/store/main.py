# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import base64
import contextlib
import functools
import inspect
import sys
import threading
import weakref
from asyncio import Handle, iscoroutine
from datetime import datetime
from pathlib import Path
from types import GenericAlias
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    TypeAlias,
    TypeVar,
    cast,
    get_origin,
    overload,
)

import dill
from fake import Fake
from immutable import Immutable
from redux import (
    BaseCombineReducerState,
    CombineReducerAction,
    CombineReducerRegisterAction,
    CreateStoreOptions,
    FinishAction,
    InitAction,
    Store,
    combine_reducers,
)
from redux.basic_types import StrictEvent, SubscribeEventCleanup

from ubo_app.constants import DEBUG_MODE, STORE_GRACE_PERIOD
from ubo_app.logger import logger
from ubo_app.store.core.types import MainAction, MainEvent
from ubo_app.store.input.reducer import reducer as input_reducer
from ubo_app.store.input.types import (
    InputAction,
    InputResolveEvent,
)
from ubo_app.store.schedular import Scheduler
from ubo_app.store.services.audio import AudioAction, AudioEvent
from ubo_app.store.services.camera import CameraAction, CameraEvent
from ubo_app.store.services.display import DisplayAction, DisplayEvent
from ubo_app.store.services.docker import DockerAction
from ubo_app.store.services.ip import IpAction, IpEvent
from ubo_app.store.services.keypad import KeypadAction
from ubo_app.store.services.lightdm import LightDMAction
from ubo_app.store.services.notifications import (
    NotificationsAction,
    NotificationsEvent,
)
from ubo_app.store.services.rgb_ring import RgbRingAction
from ubo_app.store.services.rpi_connect import RPiConnectAction
from ubo_app.store.services.sensors import SensorsAction
from ubo_app.store.services.ssh import SSHAction
from ubo_app.store.services.users import UsersAction, UsersEvent
from ubo_app.store.services.voice import VoiceAction
from ubo_app.store.services.vscode import VSCodeAction
from ubo_app.store.services.wifi import WiFiAction, WiFiEvent
from ubo_app.store.settings.reducer import reducer as settings_reducer
from ubo_app.store.settings.types import SettingsAction, SettingsState
from ubo_app.store.status_icons.reducer import reducer as status_icons_reducer
from ubo_app.store.status_icons.types import StatusIconsAction
from ubo_app.store.update_manager.reducer import reducer as update_manager_reducer
from ubo_app.store.update_manager.types import UpdateManagerAction
from ubo_app.utils.async_ import get_task_runner
from ubo_app.utils.serializer import add_type_field

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from redux.basic_types import (
        EventHandler,
        SnapshotAtom,
        TaskCreatorCallback,
    )

    from ubo_app.store.core.types import MainState
    from ubo_app.store.services.audio import AudioState
    from ubo_app.store.services.camera import CameraState
    from ubo_app.store.services.display import DisplayState
    from ubo_app.store.services.docker import DockerState
    from ubo_app.store.services.ip import IpState
    from ubo_app.store.services.lightdm import LightDMState
    from ubo_app.store.services.notifications import NotificationsState
    from ubo_app.store.services.rgb_ring import RgbRingState
    from ubo_app.store.services.rpi_connect import RPiConnectState
    from ubo_app.store.services.sensors import SensorsState
    from ubo_app.store.services.ssh import SSHState
    from ubo_app.store.services.users import UsersState
    from ubo_app.store.services.voice import VoiceState
    from ubo_app.store.services.vscode import VSCodeState
    from ubo_app.store.services.web_ui import WebUIState
    from ubo_app.store.services.wifi import WiFiState
    from ubo_app.store.status_icons.types import StatusIconsState
    from ubo_app.store.update_manager.types import UpdateManagerState

UboAction: TypeAlias = (
    # Core Actions
    CombineReducerAction
    | InitAction
    | FinishAction
    | MainAction
    | SettingsAction
    | StatusIconsAction
    | UpdateManagerAction
    | InputAction
    # Services Actions
    | AudioAction
    | CameraAction
    | DisplayAction
    | DockerAction
    | IpAction
    | KeypadAction
    | LightDMAction
    | NotificationsAction
    | RgbRingAction
    | RPiConnectAction
    | SensorsAction
    | SSHAction
    | UsersAction
    | VoiceAction
    | VSCodeAction
    | WiFiAction
)
UboEvent: TypeAlias = (
    # Core Events
    MainEvent
    | InputResolveEvent
    # Services Events
    | AudioEvent
    | CameraEvent
    | DisplayEvent
    | IpEvent
    | NotificationsEvent
    | UsersEvent
    | WiFiEvent
)

if threading.current_thread() is not threading.main_thread():
    msg = 'Store should be created in the main thread'
    raise RuntimeError(msg)


class RootState(BaseCombineReducerState):
    main: MainState
    settings: SettingsState
    status_icons: StatusIconsState
    update_manager: UpdateManagerState

    audio: AudioState
    camera: CameraState
    display: DisplayState
    docker: DockerState
    ip: IpState
    lightdm: LightDMState
    notifications: NotificationsState
    rgb_ring: RgbRingState
    rpi_connect: RPiConnectState
    sensors: SensorsState
    ssh: SSHState
    users: UsersState
    voice: VoiceState
    vscode: VSCodeState
    web_ui: WebUIState
    wifi: WiFiState


root_reducer, root_reducer_id = combine_reducers(
    state_type=RootState,
    action_type=UboAction,  # pyright: ignore [reportArgumentType]
    event_type=UboEvent,  # pyright: ignore [reportArgumentType]
    settings=settings_reducer,
    status_icons=status_icons_reducer,
    update_manager=update_manager_reducer,
    input=input_reducer,
)

T = TypeVar('T')
LoadedObject = (
    int
    | float
    | str
    | bytes
    | bool
    | None
    | Immutable
    | list['LoadedObject']
    | set['LoadedObject']
)


class InThreadEventHandler(Generic[StrictEvent]):
    def __init__(
        self: InThreadEventHandler,
        handler: EventHandler[StrictEvent],
        *,
        keep_ref: bool = True,
    ) -> None:
        self.handler_str = str(handler)
        self.__name__ = f'InThreadHandler:{self.handler_str}'
        if keep_ref:
            self.handler_ref = handler
        elif inspect.ismethod(handler):
            self.handler_ref = weakref.WeakMethod(handler)
        else:
            self.handler_ref = weakref.ref(handler)

        self.task_runner = get_task_runner()

    def __call__(self: InThreadEventHandler, event: StrictEvent) -> None:
        async def wrapper() -> None:
            if isinstance(self.handler_ref, weakref.ref):
                handler = cast('EventHandler[StrictEvent]', self.handler_ref())
                if not handler:
                    return
            else:
                handler = self.handler_ref

            parameters = 1
            with contextlib.suppress(Exception):
                parameters = len(
                    [
                        param
                        for param in inspect.signature(
                            handler,
                        ).parameters.values()
                        if param.kind
                        in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
                    ],
                )

            if parameters == 0:
                result = cast('Callable[[], Any]', handler)()
            else:
                result = cast('Callable[[StrictEvent], Any]', handler)(event)
            if iscoroutine(result):
                await result

        self.task_runner(wrapper())

    def __repr__(self: InThreadEventHandler) -> str:
        """Return a string representation of the instance containing the handler."""
        return f'<InThreadHandler:{self.handler_str}>'


class UboStore(Store[RootState, UboAction, UboEvent]):
    @classmethod
    def serialize_value(cls: type[UboStore], obj: object | type) -> SnapshotAtom:  # noqa: C901
        from redux.autorun import Autorun
        from ubo_gui.page import PageWidget

        if isinstance(obj, Autorun):
            obj = obj()
        if isinstance(obj, set):
            return {'_type': 'set', 'value': [cls.serialize_value(i) for i in obj]}
        if isinstance(obj, bytes):
            return {'_type': 'bytes', 'value': base64.b64encode(obj).decode('utf-8')}
        if isinstance(obj, datetime):
            return {'_type': 'datetime', 'value': obj.isoformat()}
        if isinstance(obj, type) and issubclass(obj, PageWidget):
            import ubo_app

            _ = ubo_app
            file_path = sys.modules[obj.__module__].__file__
            ubo_app_path = sys.modules['ubo_app'].__file__
            if file_path and ubo_app_path:
                root_path = Path(ubo_app_path).parent
                path = Path(file_path)
                return f"""{
                    (
                        path.relative_to(root_path)
                        if file_path.startswith(root_path.as_posix())
                        else path.absolute()
                    ).as_posix()
                }:{obj.__name__}"""
            return f'{obj.__module__}:{obj.__name__}'
        if isinstance(obj, functools.partial):
            return f'<functools.partial:{cls.serialize_value(obj.func)}>'
        if callable(obj):
            return f'<function:{obj.__name__}>'
        if isinstance(obj, dict):
            return {k: cls.serialize_value(v) for k, v in obj.items()}
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

    def load_object(  # noqa: C901
        self: UboStore,
        data: Any,
        *,
        object_type: GenericAlias | type[T] | None = None,
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
            if type_ == 'set':
                return {self.load_object(i) for i in data['value']}
            if type_ == 'bytes':
                return base64.b64decode(data['value'].encode('utf-8'))

            if isinstance(type_, type):
                class_ = type_
            elif isinstance(type_, str):
                class_ = dill.loads(base64.b64decode(type_.encode('utf-8')))  # noqa: S301
            else:
                msg = f'Invalid type {type(type_)}'
                raise TypeError(msg)

            parameters = {key: self.load_object(value) for key, value in data.items()}

            return class_(**parameters)
        if isinstance(object_type, GenericAlias):
            origin = get_origin(object_type)
            if isinstance(data, origin):
                return cast('T', data)
        elif not object_type or isinstance(data, object_type):
            return cast('T', data)

        msg = f'Invalid data type {type(data)}'
        raise TypeError(msg)

    def subscribe_event(
        self: UboStore,
        event_type: type[StrictEvent],
        handler: EventHandler[StrictEvent],
        *,
        keep_ref: bool = True,
    ) -> SubscribeEventCleanup:
        in_thread_handler = InThreadEventHandler(handler, keep_ref=keep_ref)

        if keep_ref:
            return super().subscribe_event(
                event_type,
                in_thread_handler,
                keep_ref=keep_ref,
            )

        # Put the in_thread_handler in the handler's reference island to tie their
        # lifetimes together
        key = f'__ubo_store_in_thread_handler:{event_type.__name__}'

        unsubscribe = super().subscribe_event(
            event_type,
            in_thread_handler,
            keep_ref=keep_ref,
        )

        def unsubscribe_() -> None:
            unsubscribe()
            handlers.remove(in_thread_handler)

        if not hasattr(handler, key):
            handler.__dict__[key] = []

        handlers = handler.__dict__[key]
        handlers.append(in_thread_handler)

        return SubscribeEventCleanup(
            unsubscribe=unsubscribe_,
            handler=in_thread_handler,
        )


def create_task(
    coro: Coroutine,
    *,
    callback: TaskCreatorCallback | None = None,
) -> None:
    from ubo_app.utils.async_ import create_task

    create_task(coro, callback)


def action_middleware(action: UboAction) -> UboAction:
    logger.debug(
        'Action dispatched',
        extra={'action': action},
    )
    return action


def event_middleware(event: UboEvent) -> UboEvent | None:
    logger.debug(
        'Event dispatched',
        extra={'event': event},
    )
    return event


scheduler = Scheduler()
scheduler.start()


store = UboStore(
    root_reducer,
    CreateStoreOptions(
        auto_init=False,
        scheduler=scheduler.set,
        action_middlewares=[action_middleware],
        event_middlewares=[event_middleware],
        task_creator=create_task,
        on_finish=scheduler.stop,
        grace_time_in_seconds=STORE_GRACE_PERIOD,
    ),
)


from ubo_app.store.core.reducer import reducer as main_reducer  # noqa: E402

store.dispatch(InitAction())
store.dispatch(
    CombineReducerRegisterAction(
        _id=root_reducer_id,
        key='main',
        reducer=main_reducer,
    ),
)

if DEBUG_MODE:
    store._subscribe(  # noqa: SLF001
        lambda state: logger.verbose('State updated', extra={'state': state}),
    )
