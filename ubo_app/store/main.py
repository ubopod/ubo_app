# ruff: noqa: D100, D101, D102, D103
from __future__ import annotations

import base64
import contextlib
import functools
import inspect
import threading
import weakref
from asyncio import Handle, iscoroutine
from enum import Flag, IntEnum, StrEnum
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
from immutable import Immutable, is_immutable
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
from ubo_app.store.core.dynamic_menus_reducer import reducer as dynamic_menus_reducer
from ubo_app.store.core.view_computation import setup_dynamic_view_autorun
from ubo_app.store.core.view_registry import register_status_bar_dependency
from ubo_app.store.input.reducer import reducer as input_reducer
from ubo_app.store.scheduler import Scheduler
from ubo_app.store.settings.reducer import reducer as settings_reducer
from ubo_app.store.status_icons.reducer import reducer as status_icons_reducer
from ubo_app.store.update_manager.reducer import reducer as update_manager_reducer
from ubo_app.utils.async_ import ToThreadOptions
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
    from store.services.file_system import FileSystemAction
    from store.settings.types import SettingsAction

    from ubo_app.store.core.types import (
        DynamicMenusState,
        MainAction,
        MainEvent,
        MainState,
    )
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
    from ubo_app.store.services.chat import ChatAction, ChatEvent, ChatState
    from ubo_app.store.services.display import DisplayAction, DisplayEvent, DisplayState
    from ubo_app.store.services.docker import DockerAction, DockerState
    from ubo_app.store.services.file_system import FileSystemEvent
    from ubo_app.store.services.infrared import (
        InfraredAction,
        InfraredEvent,
        InfraredState,
    )
    from ubo_app.store.services.ip import IpAction, IpEvent, IpState
    from ubo_app.store.services.keypad import (
        KeypadAction,
        KeypadReportContextAction,
        KeypadState,
    )
    from ubo_app.store.services.lightdm import LightDMAction, LightDMState
    from ubo_app.store.services.localization import (
        LocalizationAction,
        LocalizationEvent,
        LocalizationState,
    )
    from ubo_app.store.services.mcp import McpAction, McpEvent, McpState
    from ubo_app.store.services.mqtt import MqttAction, MqttEvent, MqttState
    from ubo_app.store.services.notifications import (
        NotificationsAction,
        NotificationsEvent,
        NotificationsState,
    )
    from ubo_app.store.services.rgb_ring import RgbRingAction, RgbRingState
    from ubo_app.store.services.rpi_connect import RPiConnectAction, RPiConnectState
    from ubo_app.store.services.sensors import (
        SensorsAction,
        SensorsEvent,
        SensorsState,
    )
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
    from ubo_app.store.services.system import SystemAction, SystemState
    from ubo_app.store.services.tailscale import TailscaleAction, TailscaleState
    from ubo_app.store.services.users import UsersAction, UsersEvent, UsersState
    from ubo_app.store.services.vscode import VSCodeAction, VSCodeState
    from ubo_app.store.services.web_ui import WebUIAction, WebUIState
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
    'ChatAction',
    'DisplayAction',
    'DockerAction',
    'FileSystemAction',
    'InfraredAction',
    'IpAction',
    'KeypadAction',
    'KeypadReportContextAction',
    'LightDMAction',
    'LocalizationAction',
    'McpAction',
    'MqttAction',
    'NotificationsAction',
    'RgbRingAction',
    'RPiConnectAction',
    'SensorsAction',
    'SystemAction',
    'SpeechRecognitionAction',
    'SpeechSynthesisAction',
    'SSHAction',
    'TailscaleAction',
    'UsersAction',
    'VSCodeAction',
    'WebUIAction',
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
    'ChatEvent',
    'DisplayEvent',
    'FileSystemEvent',
    'InfraredEvent',
    'IpEvent',
    'LocalizationEvent',
    'McpEvent',
    'MqttEvent',
    'NotificationsEvent',
    'SensorsEvent',
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
    dynamic_menus: DynamicMenusState

    assistant: AssistantState
    audio: AudioState
    camera: CameraState
    chat: ChatState
    display: DisplayState
    docker: DockerState
    infrared: InfraredState
    ip: IpState
    keypad: KeypadState
    lightdm: LightDMState
    localization: LocalizationState
    mcp: McpState
    mqtt: MqttState
    notifications: NotificationsState
    rgb_ring: RgbRingState
    rpi_connect: RPiConnectState
    sensors: SensorsState
    speech_recognition: SpeechRecognitionState
    system: SystemState
    speech_synthesis: SpeechSynthesisState
    ssh: SSHState
    tailscale: TailscaleState
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
    dynamic_menus=dynamic_menus_reducer,
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


def _is_page_widget(obj: object) -> bool:
    """Check if obj is a PageWidget without importing kivy."""
    for cls in type(obj).__mro__:
        if cls.__module__.startswith('ubo_gui.page') and cls.__name__ == 'PageWidget':
            return True
    return False


class UboStore(Store[RootState, UboAction, UboEvent]):
    @classmethod
    def serialize_value(cls: type[UboStore], obj: object | type) -> SnapshotAtom:
        from redux.autorun import Autorun

        if isinstance(obj, Autorun):
            obj = obj()
        if isinstance(obj, Flag):
            return obj.value
        if isinstance(obj, bytes):
            return {'_type': 'bytes', 'value': base64.b64encode(obj).decode('utf-8')}
        if isinstance(obj, functools.partial):
            return f'<functools.partial:{cls.serialize_value(obj.func)}>'
        if is_immutable(obj):
            return cls._serialize_dataclass_to_dict(obj)
        if callable(obj):
            return f'<function:{obj.__name__}>'
        if isinstance(obj, dict):
            return {k: cls.serialize_value(v) for k, v in obj.items()}
        if isinstance(obj, Handle | Fake) or _is_page_widget(obj):
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

    def load_object(  # noqa: C901, PLR0912
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
        elif object_type and issubclass(object_type, StrEnum):
            if isinstance(data, str):
                return object_type(data)
            msg = f'Invalid data type {type(data)} for StrEnum {object_type}'
            raise TypeError(msg)
        elif object_type and issubclass(object_type, IntEnum):
            if isinstance(data, int):
                return object_type(data)
            msg = f'Invalid data type {type(data)} for IntEnum {object_type}'
            raise TypeError(msg)
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

    # Maximum actions to process before checking for events
    # Lower = more responsive events, higher = better action throughput
    ACTIONS_PER_EVENT_CHECK = 50

    def run(self: Self) -> None:
        """Override to interleave action and event processing.

        The base _run_actions() has an internal while loop that processes
        ALL queued actions, preventing interleaving. This override inlines
        the action processing logic to process N actions, then ALL pending
        events, then repeat.
        """
        from redux import is_complete_reducer_result, is_state_reducer_result
        from redux.basic_types import FinishAction, FinishEvent

        with self._is_running:
            while len(self._actions) > 0 or len(self._events) > 0:
                # Process a batch of actions (up to ACTIONS_PER_EVENT_CHECK)
                actions_processed = 0
                while (
                    len(self._actions) > 0
                    and actions_processed < self.ACTIONS_PER_EVENT_CHECK
                ):
                    action = self._actions.pop(0)
                    if action is not None:
                        result = self.reducer(self._state, action)
                        if is_complete_reducer_result(result):
                            self._state = result.state
                            if self._state is not None:
                                self._call_listeners(self._state)
                            self._dispatch(
                                [*(result.actions or []), *(result.events or [])],
                            )
                        elif is_state_reducer_result(result):
                            self._state = result
                            if self._state is not None:
                                self._call_listeners(self._state)

                        if isinstance(action, FinishAction):
                            self._dispatch([FinishEvent()])

                    actions_processed += 1

                # Process ALL pending events before continuing with actions
                if len(self._events) > 0:
                    self._run_event_handlers()



CALL_EVENT_KWARGS_KEY = '__ubo_autorun_call_event'


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
        # Reactions are dispatched to a thread pool (see ``call`` below), so without
        # serialization the *same* autorun can run its reaction concurrently with
        # itself. Several services rebuild menus from a reaction by unregistering then
        # re-registering ids in the process-wide action registry (a check-then-act
        # that is not atomic); concurrent reactions race and raise
        # ``ValueError: ... already registered``. This lock serializes an autorun's
        # own reactions while leaving distinct autoruns free to run in parallel.
        self._reaction_lock = threading.Lock()

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
        call_event: threading.Event | None = cast(
            'threading.Event',
            kwargs.pop(CALL_EVENT_KWARGS_KEY, None),
        )

        def wrapper(super_: Autorun) -> None:
            try:
                with self._reaction_lock:
                    super_.call(*args, **kwargs)
            except Exception:
                logger.exception(
                    'Error in autorun call',
                    extra={
                        'autorun': self,
                        'args_': args,
                        'kwargs': kwargs,
                    },
                )
                report_service_error()
            finally:
                if call_event:
                    call_event.set()

        from ubo_app.utils.async_ import to_thread

        to_thread(
            wrapper,
            ToThreadOptions(coroutine_runner=self.coroutine_runner),
            super_=super(),
        )

    def __call__(
        self: Self,
        *args: Args.args,
        **kwargs: Args.kwargs,
    ) -> ReturnType:
        call_event = threading.Event()
        super().__call__(*args, **{**kwargs, CALL_EVENT_KWARGS_KEY: call_event})
        if not call_event.wait(timeout=30):
            report_service_error(
                exception=RuntimeError('Autorun call timed out after 30 seconds'),
            )
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

# Register status icons as a view dependency for status bar updates
register_status_bar_dependency(
    'status_icons',
    lambda s: tuple(s.status_icons.icons) if hasattr(s, 'status_icons') else (),
)

# Set up core dynamic menus (home, main, settings, apps, power, etc.)
from ubo_app.store.core.menus import setup_core_dynamic_menus  # noqa: E402

setup_core_dynamic_menus()

# Set up dynamic view computation for dumb UI architecture
setup_dynamic_view_autorun()

store._subscribe(  # noqa: SLF001
    lambda state: logger.verbose('State updated', extra={'state': state}),
)
