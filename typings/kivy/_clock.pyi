from typing import Any, Callable, List, Optional, Union

class ClockNotRunningError(RuntimeError): ...

class ClockEvent:
    next: Optional[ClockEvent]
    prev: Optional[ClockEvent]
    cid: Optional[Any]
    clock: CyClockBase
    loop: int
    weak_callback: Optional[Any] # Actually WeakMethod, but Any for simplicity here
    callback: Optional[Callable[[float], Optional[bool]]]
    timeout: float
    _last_dt: float
    _dt: float
    _del_queue: List[Any] # Type of elements in _del_queue is not specified
    clock_ended_callback: Optional[Callable[["ClockEvent"], None]]
    weak_clock_ended_callback: Optional[Any] # Actually WeakMethod
    release_ref: int
    _is_triggered: int # From .pyx, but good to have for understanding

    def __init__(
        self,
        clock: CyClockBase,
        loop: int,
        callback: Callable[[float], Optional[bool]],
        timeout: float,
        starttime: float,
        cid: Optional[Any] = None,
        trigger: bool = False,
        clock_ended_callback: Optional[Callable[["ClockEvent"], None]] = None,
        release_ref: bool = True,
    ) -> None: ...
    def __call__(self, *largs: Any) -> None: ...
    def get_callback(self) -> Optional[Callable[[float], Optional[bool]]]: ...
    def get_clock_ended_callback(self) -> Optional[Callable[["ClockEvent"], None]]: ...
    @property
    def is_triggered(self) -> bool: ...
    def cancel(self) -> None: ...
    def release(self) -> None: ...
    def tick(self, curtime: float) -> Optional[bool]: ...  # Return type can be bool or None if loop is False

class FreeClockEvent(ClockEvent):
    free: int

    def __init__(
        self,
        free: bool, # from .pyx
        clock: CyClockBase, # from .pyx ClockEvent.__init__
        loop: int, # from .pyx ClockEvent.__init__
        callback: Callable[[float], Optional[bool]], # from .pyx ClockEvent.__init__
        timeout: float, # from .pyx ClockEvent.__init__
        starttime: float, # from .pyx ClockEvent.__init__
        cid: Optional[Any] = None, # from .pyx ClockEvent.__init__
        trigger: bool = False, # from .pyx ClockEvent.__init__
        clock_ended_callback: Optional[Callable[["ClockEvent"], None]] = None, # from .pyx ClockEvent.__init__
        release_ref: bool = True, # from .pyx ClockEvent.__init__
    ) -> None: ...


class CyClockBase:
    _last_tick: float
    max_iteration: int
    clock_resolution: float
    _max_fps: float # From .pyx __cinit__
    _root_event: Optional[ClockEvent]
    _next_event: Optional[ClockEvent]
    _cap_event: Optional[ClockEvent]
    _last_event: Optional[ClockEvent]
    _lock: Any # threading.Lock
    _lock_acquire: Callable[[], bool]
    _lock_release: Callable[[], None]
    has_started: int
    has_ended: int
    _del_safe_lock: Any # threading.RLock
    _del_safe_done: int # bool in practice
    _del_queue: List[tuple[Callable[[], None], Optional[Callable[[Callable[[], None]], None]]]] # from .pyx

    def __init__(self, **kwargs: Any) -> None: ...
    def start_clock(self) -> None: ...
    def stop_clock(self) -> None: ...
    def get_resolution(self) -> float: ...
    def on_schedule(self, event: ClockEvent) -> None: ...
    def create_lifecycle_aware_trigger(
        self,
        callback: Callable[[float], Optional[bool]],
        clock_ended_callback: Callable[[ClockEvent], None],
        timeout: float = 0,
        interval: bool = False,
        release_ref: bool = True,
    ) -> ClockEvent: ...
    def create_trigger(
        self,
        callback: Callable[[float], Optional[bool]],
        timeout: float = 0,
        interval: bool = False,
        release_ref: bool = True,
    ) -> ClockEvent: ...
    def schedule_lifecycle_aware_del_safe(
        self,
        callback: Callable[[], None],
        clock_ended_callback: Callable[[Callable[[], None]], None],
    ) -> None: ...
    def schedule_del_safe(self, callback: Callable[[], None]) -> None: ...
    def schedule_once(
        self, callback: Callable[[float], Optional[bool]], timeout: float = 0
    ) -> ClockEvent: ...
    def schedule_interval(
        self, callback: Callable[[float], Optional[bool]], timeout: float
    ) -> ClockEvent: ...
    def unschedule(
        self, callback: Union[ClockEvent, Callable[[float], Optional[bool]]], all: bool = True
    ) -> None: ...
    def _release_references(self) -> None: ...
    def _process_del_safe_events(self) -> None: ...
    def _process_events(self) -> None: ...
    def _process_events_before_frame(self) -> None: ...
    def get_min_timeout(self) -> float: ...
    def get_events(self) -> List[ClockEvent]: ...
    def get_before_frame_events(self) -> List[ClockEvent]: ...
    def handle_exception(self, e: BaseException) -> None: ...
    def _process_clock_ended_del_safe_events(self) -> None: ...
    def _process_clock_ended_callbacks(self) -> None: ...

class CyClockBaseFree(CyClockBase):
    # Methods overridden to return FreeClockEvent
    def create_lifecycle_aware_trigger(
        self,
        callback: Callable[[float], Optional[bool]],
        clock_ended_callback: Callable[[ClockEvent], None], # Should be FreeClockEvent?
        timeout: float = 0,
        interval: bool = False,
        release_ref: bool = True,
    ) -> FreeClockEvent: ... # Overridden from .pyx
    def create_trigger(
        self,
        callback: Callable[[float], Optional[bool]],
        timeout: float = 0,
        interval: bool = False,
        release_ref: bool = True,
    ) -> FreeClockEvent: ... # Overridden from .pyx
    def schedule_once(
        self, callback: Callable[[float], Optional[bool]], timeout: float = 0
    ) -> FreeClockEvent: ... # Overridden from .pyx
    def schedule_interval(
        self, callback: Callable[[float], Optional[bool]], timeout: float
    ) -> FreeClockEvent: ... # Overridden from .pyx

    # New methods specific to CyClockBaseFree
    def create_lifecycle_aware_trigger_free(
        self,
        callback: Callable[[float], Optional[bool]],
        clock_ended_callback: Callable[[FreeClockEvent], None],
        timeout: float = 0,
        interval: bool = False,
        release_ref: bool = True,
    ) -> FreeClockEvent: ...
    def create_trigger_free(
        self,
        callback: Callable[[float], Optional[bool]],
        timeout: float = 0,
        interval: bool = False,
        release_ref: bool = True,
    ) -> FreeClockEvent: ...
    def schedule_once_free(
        self, callback: Callable[[float], Optional[bool]], timeout: float = 0
    ) -> FreeClockEvent: ...
    def schedule_interval_free(
        self, callback: Callable[[float], Optional[bool]], timeout: float
    ) -> FreeClockEvent: ...
    def _process_free_events(self, last_tick: float) -> None: ...
    def get_min_free_timeout(self) -> float: ...

# Constants from .pyx
DBL_MAX: float
