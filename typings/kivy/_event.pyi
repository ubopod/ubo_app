from typing import (
    Any,
    Callable,
    Dict,
    List,
    Tuple,
    Optional,
    Union,
    TypeVar,
    overload,
    Literal,
    Type,
    Iterable,
    KeysView,
    Set,
)

from kivy.weakproxy import WeakProxy
from kivy.properties import (
    Property,
    ObjectProperty,
    NumericProperty,
    StringProperty,
    ListProperty,
    DictProperty,
    BooleanProperty,
)
from kivy.utils import deprecated

__all__ = ["EventDispatcher", "ObjectWithUid", "Observable"]

_SelfObjectWithUid = TypeVar("_SelfObjectWithUid", bound="ObjectWithUid")
_SelfObservable = TypeVar("_SelfObservable", bound="Observable")
_SelfEventDispatcher = TypeVar("_SelfEventDispatcher", bound="EventDispatcher")

class ObjectWithUid:
    """
    (internal) This class assists in providing unique identifiers for class
    instances. It is not intended for direct usage.
    """
    @property
    def uid(self) -> int: ...

    def __init__(self: _SelfObjectWithUid) -> None: ...

class Observable(ObjectWithUid):
    """:class:`Observable` is a stub class defining the methods required
    for binding. :class:`EventDispatcher` is (the) one example of a class that
    implements the binding interface. See :class:`EventDispatcher` for details.

    .. versionadded:: 1.9.0
    """
    bound_uid: int
    # __fbind_mapping: defaultdict[str, list[tuple[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]], int, Callable[..., Any]]]]

    def __init__(self: _SelfObservable, *largs: Any, **kwargs: Any) -> None: ...
    def bind(self: _SelfObservable, **kwargs: Callable[..., Any]) -> None: ...
    def unbind(self: _SelfObservable, **kwargs: Callable[..., Any]) -> None: ...
    def fbind(
        self: _SelfObservable, name: str, func: Callable[..., Any], *largs: Any, **kwargs: Any
    ) -> int: ...
    def funbind(
        self: _SelfObservable, name: str, func: Callable[..., Any], *largs: Any, **kwargs: Any
    ) -> None: ...
    def unbind_uid(self: _SelfObservable, name: str, uid: int) -> None: ...

    @property
    def proxy_ref(self: _SelfObservable) -> _SelfObservable: ...

class EventDispatcher(ObjectWithUid):
    """Generic event dispatcher interface.

    See the module docstring for usage.
    """
    # Public attributes from .pxd
    _kwargs_applied_init: Set[str]
    _proxy_ref: Optional[WeakProxy["EventDispatcher"]]

    # Typically provided by subclasses like Widget, used by dispatch_children
    children: List[Any]

    # Internal attributes, not part of public .pyi,
    # but listed for completeness of understanding from .pyx/.pxd
    # __event_stack: Dict[str, EventObservers]
    # __properties: Dict[str, Property[Any]]
    # __storage: Dict[str, PropertyStorage] # PropertyStorage is not defined here, assume internal or from kivy.properties

    def __init__(self: _SelfEventDispatcher, **kwargs: Any) -> None: ...
    def register_event_type(self: _SelfEventDispatcher, event_type: str) -> None: ...

    @deprecated(msg="Deprecated in 2.1.0, use unregister_event_type instead. Will be removed after two releases")
    def unregister_event_types(self: _SelfEventDispatcher, event_type: str) -> None: ...

    def unregister_event_type(self: _SelfEventDispatcher, event_type: str) -> None: ...
    def is_event_type(self: _SelfEventDispatcher, event_type: str) -> bool: ...
    def bind(self: _SelfEventDispatcher, **kwargs: Callable[..., Any]) -> None: ...
    def unbind(self: _SelfEventDispatcher, **kwargs: Callable[..., Any]) -> None: ...
    def fbind(
        self: _SelfEventDispatcher, name: str, func: Callable[..., Any], *largs: Any, **kwargs: Any
    ) -> int: ...
    def funbind(
        self: _SelfEventDispatcher, name: str, func: Callable[..., Any], *largs: Any, **kwargs: Any
    ) -> None: ...
    def unbind_uid(self: _SelfEventDispatcher, name: str, uid: int) -> None: ...

    @overload
    def get_property_observers(
        self: _SelfEventDispatcher, name: str, args: Literal[False] = False
    ) -> List[Callable[..., Any]]: ...
    @overload
    def get_property_observers(
        self: _SelfEventDispatcher, name: str, args: Literal[True]
    ) -> List[Tuple[Callable[..., Any], Tuple[Any, ...], Dict[str, Any], bool, Optional[int]]]: ...
    def get_property_observers(
        self: _SelfEventDispatcher, name: str, args: bool = False
    ) -> Union[
        List[Callable[..., Any]],
        List[Tuple[Callable[..., Any], Tuple[Any, ...], Dict[str, Any], bool, Optional[int]]]
    ]: ...

    def events(self: _SelfEventDispatcher) -> KeysView[str]: ...
    def dispatch(
        self: _SelfEventDispatcher, event_type: str, *largs: Any, **kwargs: Any
    ) -> Optional[bool]: ...
    def dispatch_generic(
        self: _SelfEventDispatcher, event_type: str, *largs: Any, **kwargs: Any
    ) -> Optional[bool]: ...
    def dispatch_children(
        self: _SelfEventDispatcher, event_type: str, *largs: Any, **kwargs: Any
    ) -> Optional[bool]: ...

    def setter(self: _SelfEventDispatcher, name: str) -> Callable[[_SelfEventDispatcher, Any], None]: ...
    def getter(self: _SelfEventDispatcher, name: str) -> Callable[[_SelfEventDispatcher], Any]: ...

    def property(
        self: _SelfEventDispatcher, name: str, quiet: bool = False
    ) -> Optional[Property[Any]]: ...

    def properties(self: _SelfEventDispatcher) -> Dict[str, Property[Any]]: ...

    def create_property(
        self: _SelfEventDispatcher,
        name: str,
        value: Any = None,
        default_value: bool = True,
        *largs: Any,
        **kwargs: Any
    ) -> None: ...
    def apply_property(self: _SelfEventDispatcher, **kwargs: Property[Any]) -> None: ...

    @property
    def proxy_ref(self: _SelfEventDispatcher) -> WeakProxy[_SelfEventDispatcher]: ...

    @property
    def __self__(self: _SelfEventDispatcher) -> _SelfEventDispatcher: ...

# cdef classes BoundCallback and EventObservers are internal implementation details
# and are not part of the public API surfaced in __all__.
# Their structure (from .pxd) informs the return type of get_property_observers(args=True):
# cdef class BoundCallback:
#     cdef object func -> Callable[..., Any]
#     cdef tuple largs -> Tuple[Any, ...]
#     cdef dict kwargs -> Dict[str, Any]
#     cdef int is_ref  -> bool
#     cdef object uid -> Optional[int]
#     ...
