# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import base64
import contextlib
import functools
import inspect
import threading
import weakref
from asyncio import Handle, iscoroutine
from datetime import datetime
from enum import Flag
from types import GenericAlias
from typing import (
    TYPE_CHECKING,
    Any,
    Concatenate,
    Generic,
    Self,
    TypeAlias,
    TypeVar,
    Union,
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
    FinishAction,
    FinishEvent,
    InitAction,
    Store,
    StoreOptions,
    combine_reducers,
)
from redux.autorun import Autorun
from redux.basic_types import (
    Args,
    AutoAwait,
    AutorunOptionsType,
    ReturnType,
    SelectorOutput,
    StrictEvent,
    SubscribeEventCleanup,
)

from ubo_app.constants import STORE_GRACE_PERIOD
from ubo_app.logger import logger
from ubo_app.store.input.reducer import reducer as input_reducer
from ubo_app.store.scheduler import Scheduler
from ubo_app.store.settings.reducer import reducer as settings_reducer
from ubo_app.store.status_icons.reducer import reducer as status_icons_reducer
from ubo_app.store.update_manager.reducer import reducer as update_manager_reducer
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.serializer import add_type_field
from ubo_app.utils.service import get_coroutine_runner

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from redux.basic_types import (
        EventHandler,
        SnapshotAtom,
        TaskCreatorCallback,
    )
    from store.settings.types import SettingsAction

    from ubo_app.store.core.types import MainAction, MainEvent, MainState
    from ubo_app.store.input.types import (
        InputAction,
        InputResolveEvent,
    )
    from ubo_app.store.services.assistant import (
        AssistantAction,
        AssistantEvent,
        AssistantState,
    )
    from ubo_app.store.services.audio import AudioAction, AudioEvent, AudioState
    from ubo_app.store.services.camera import CameraAction, CameraEvent, CameraState
    from ubo_app.store.services.display import DisplayAction, DisplayEvent, DisplayState
    from ubo_app.store.services.docker import DockerAction, DockerState
    from ubo_app.store.services.infrared import (
        InfraredAction,
        InfraredEvent,
        InfraredState,
    )
    from ubo_app.store.services.ip import IpAction, IpEvent, IpState
    from ubo_app.store.services.keypad import KeypadAction
    from ubo_app.store.services.lightdm import LightDMAction, LightDMState
    from ubo_app.store.services.notifications import (
        NotificationsAction,
        NotificationsEvent,
        NotificationsState,
    )
    from ubo_app.store.services.rgb_ring import RgbRingAction, RgbRingState
    from ubo_app.store.services.rpi_connect import RPiConnectAction, RPiConnectState
    from ubo_app.store.services.sensors import SensorsAction, SensorsState
    from ubo_app.store.services.speech_recognition import (
        SpeechRecognitionAction,
        SpeechRecognitionEvent,
        SpeechRecognitionState,
    )
    from ubo_app.store.services.speech_synthesis import (
        SpeechSynthesisAction,
        SpeechSynthesisState,
    )
    from ubo_app.store.services.ssh import SSHAction, SSHState
    from ubo_app.store.services.users import UsersAction, UsersEvent, UsersState
    from ubo_app.store.services.vscode import VSCodeAction, VSCodeState
    from ubo_app.store.services.web_ui import WebUIState
    from ubo_app.store.services.wifi import WiFiAction, WiFiEvent, WiFiState
    from ubo_app.store.settings.types import SettingsState
    from ubo_app.store.status_icons.types import StatusIconsAction, StatusIconsState
    from ubo_app.store.update_manager.types import (
        UpdateManagerAction,
        UpdateManagerState,
    )

UboAction: TypeAlias = Union[
    # Core Actions
    'CombineReducerAction',
    'InitAction',
    'FinishAction',
    'MainAction',
    'SettingsAction',
    'StatusIconsAction',
    'UpdateManagerAction',
    'InputAction',
    # Services Actions
    'AssistantAction',
    'AudioAction',
    'CameraAction',
    'DisplayAction',
    'DockerAction',
    'InfraredAction',
    'IpAction',
    'KeypadAction',
    'LightDMAction',
    'NotificationsAction',
    'RgbRingAction',
    'RPiConnectAction',
    'SensorsAction',
    'SpeechRecognitionAction',
    'SpeechSynthesisAction',
    'SSHAction',
    'UsersAction',
    'VSCodeAction',
    'WiFiAction',
]
UboEvent: TypeAlias = Union[
    # Core Events
    'MainEvent',
    'InputResolveEvent',
    # Services Events
    'AssistantEvent',
    'AudioEvent',
    'CameraEvent',
    'DisplayEvent',
    'InfraredEvent',
    'IpEvent',
    'NotificationsEvent',
    'SpeechRecognitionEvent',
    'UsersEvent',
    'WiFiEvent',
]

if threading.current_thread() is not threading.main_thread():
    msg = 'Store should be created in the main thread'
    raise RuntimeError(msg)


class RootState(BaseCombineReducerState):
    main: MainState
    settings: SettingsState
    status_icons: StatusIconsState
    update_manager: UpdateManagerState

    assistant: AssistantState
    audio: AudioState
    camera: CameraState
    display: DisplayState
    docker: DockerState
    infrared: InfraredState
    ip: IpState
    lightdm: LightDMState
    notifications: NotificationsState
    rgb_ring: RgbRingState
    rpi_connect: RPiConnectState
    sensors: SensorsState
    speech_recognition: SpeechRecognitionState
    speech_synthesis: SpeechSynthesisState
    ssh: SSHState
    users: UsersState
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


class _UboEventHandler(Generic[StrictEvent]):
    def __init__(
        self: Self,
        handler: EventHandler[StrictEvent],
        *,
        keep_ref: bool = True,
    ) -> None:
        self.handler_str = str(handler)
        self.handler_name = handler.__name__
        self.handler_qualname = handler.__qualname__
        self.__name__ = f'UboEventHandler:{self.handler_str}'
        self.__qualname__ = f'UboEventHandler:{self.handler_qualname}'
        if keep_ref:
            self.handler_ref = handler
        elif inspect.ismethod(handler):
            self.handler_ref = weakref.WeakMethod(handler)
        else:
            self.handler_ref = weakref.ref(handler)

        self.coroutine_runner = get_coroutine_runner()

    def __call__(self: Self, event: StrictEvent) -> None:
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

        coroutine = wrapper()
        coroutine.__name__ = f'UboEventHandler:wrapped-coroutine:{self.handler_name}'
        coroutine.__qualname__ = (
            f'UboEventHandler:wrapped-coroutine:{self.handler_qualname}'
        )
        from ubo_app.utils.async_ import create_task

        create_task(coroutine, coroutine_runner=self.coroutine_runner)

    def __repr__(self: Self) -> str:
        """Return a string representation of the instance containing the handler."""
        return f'<UboEventHandler:{self.handler_str}>'


class UboStore(Store[RootState, UboAction, UboEvent]):
    @classmethod
    def serialize_value(cls: type[UboStore], obj: object | type) -> SnapshotAtom:
        from redux.autorun import Autorun
        from ubo_gui.page import PageWidget

        if isinstance(obj, Autorun):
            obj = obj()
        if isinstance(obj, Flag):
            return obj.value
        if isinstance(obj, set):
            return {'_type': 'set', 'value': [cls.serialize_value(i) for i in obj]}
        if isinstance(obj, bytes):
            return {'_type': 'bytes', 'value': base64.b64encode(obj).decode('utf-8')}
        if isinstance(obj, datetime):
            return {'_type': 'datetime', 'value': obj.isoformat()}
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
        self: Self,
        data: SnapshotAtom,
    ) -> int | float | str | bool | None | Immutable: ...
    @overload
    def load_object(
        self: Self,
        data: SnapshotAtom,
        *,
        object_type: type[T],
    ) -> T: ...

    def load_object(  # noqa: C901
        self: Self,
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
        self: Self,
        event_type: type[StrictEvent],
        handler: EventHandler[StrictEvent],
        *,
        keep_ref: bool = True,
    ) -> SubscribeEventCleanup:
        in_thread_handler = _UboEventHandler(handler, keep_ref=keep_ref)

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


class _UboAutorun(
    Autorun[
        RootState,
        UboAction,
        UboEvent,
        SelectorOutput,
        Any,
        Args,
        ReturnType,
    ],
    Generic[
        SelectorOutput,
        Args,
        ReturnType,
    ],
):
    def __init__(
        self: Self,
        *,
        store: UboStore,
        selector: Callable[[RootState], SelectorOutput],
        comparator: Callable[[RootState], Any] | None,
        func: Callable[
            Concatenate[SelectorOutput, Args],
            ReturnType,
        ],
        options: AutorunOptionsType[ReturnType, AutoAwait],
    ) -> None:
        self.handler_str = str(func)
        self.handler_name = func.__name__
        self.handler_qualname = func.__qualname__
        self.__name__ = f'UboAutorun:{self.handler_str}'
        self.__qualname__ = f'UboAutorun:{self.handler_qualname}'
        if options.keep_ref:
            self.handler_ref = func
        elif inspect.ismethod(func):
            self.handler_ref = weakref.WeakMethod(func)
        else:
            self.handler_ref = weakref.ref(func)

        self.coroutine_runner = get_coroutine_runner()
        self.call_event = threading.Event()

        super().__init__(
            store=store,
            selector=selector,
            comparator=comparator,
            func=func,
            options=options,
        )

    def call(
        self: Self,
        *args: Args.args,
        **kwargs: Args.kwargs,
    ) -> None:
        def wrapper(super_: Autorun) -> None:
            try:
                super_.call(*args, **kwargs)
            except Exception:  # noqa: BLE001
                report_service_error()
            finally:
                self.call_event.set()

        from ubo_app.utils.async_ import to_thread_with_coroutine_runner

        to_thread_with_coroutine_runner(
            wrapper,
            coroutine_runner=self.coroutine_runner,
            super_=super(),
        )

    def __call__(
        self: Self,
        *args: Args.args,
        **kwargs: Args.kwargs,
    ) -> ReturnType:
        self.call_event.clear()
        super().__call__(*args, **kwargs)
        return self._latest_value

    def _create_task(self, coro: Coroutine[None, None, Any]) -> None:
        self.coroutine_runner(coro)


def ubo_create_task(
    coro: Coroutine,
    *,
    callback: TaskCreatorCallback | None = None,
) -> None:
    from ubo_app.utils.async_ import create_task

    create_task(coro, callback)


def action_middleware(action: UboAction) -> UboAction:
    logger.verbose(
        'Action dispatched',
        extra={'action': action},
    )
    return action


def event_middleware(event: UboEvent | FinishEvent) -> UboEvent | FinishEvent | None:
    logger.verbose(
        'Event dispatched',
        extra={'event': event},
    )
    return event


scheduler = Scheduler()
scheduler.start()


store = UboStore(
    root_reducer,
    StoreOptions(
        auto_init=False,
        scheduler=scheduler.set,
        action_middlewares=[action_middleware],
        event_middlewares=[event_middleware],
        task_creator=ubo_create_task,
        on_finish=scheduler.stop,
        grace_time_in_seconds=STORE_GRACE_PERIOD,
        autorun_class=_UboAutorun,
    ),
)


from ubo_app.store.core.reducer import reducer as main_reducer  # noqa: E402

store.dispatch(InitAction())
store.dispatch(
    CombineReducerRegisterAction(
        combine_reducers_id=root_reducer_id,
        key='main',
        reducer=main_reducer,
    ),
)

store._subscribe(  # noqa: SLF001
    lambda state: logger.verbose('State updated', extra={'state': state}),
)
