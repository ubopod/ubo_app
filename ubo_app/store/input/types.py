"""Type definitions for the Redux store operations."""

from __future__ import annotations

from enum import Flag, FlagBoundary, StrEnum, auto
from typing import IO, TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from io import BytesIO

    from ubo_app.store.services.speech_synthesis import ReadableInformation


class InputResult(Immutable):
    """Input result."""

    data: dict[str, str | None]
    files: dict[str, IO[bytes] | BytesIO]
    method: InputMethod


class InputFieldType(StrEnum):
    """Enumeration of input field types."""

    LONG = 'long'
    TEXT = 'text'
    PASSWORD = 'password'  # noqa: S105
    NUMBER = 'number'
    CHECKBOX = 'checkbox'
    COLOR = 'color'
    SELECT = 'select'
    FILE = 'file'
    DATE = 'date'
    TIME = 'time'


class InputMethod(Flag, boundary=FlagBoundary.STRICT):
    """Input method."""

    CAMERA = auto()
    WEB_DASHBOARD = auto()
    ALL = CAMERA | WEB_DASHBOARD


class InputFieldDescription(Immutable):
    """Description of an input field in an input demand."""

    name: str
    label: str
    type: InputFieldType
    description: str | None = None
    title: str | None = None
    pattern: str | None = None
    default: str | None = None
    options: list[str] | None = None
    required: bool = False


class InputDescription(Immutable):
    """Description of an input demand."""

    title: str
    prompt: str | None
    extra_information: ReadableInformation | None = None
    id: str
    pattern: str | None
    fields: list[InputFieldDescription] | None = None


class InputAction(BaseAction):
    """Base class for input actions."""


class InputDemandAction(InputAction):
    """Action for demanding input from the user."""

    description: InputDescription
    method: InputMethod


class InputResolveAction(InputAction):
    """Base class for resolving input demands."""

    id: str


class InputCancelAction(InputResolveAction):
    """Action for cancelling an input demand."""


class InputProvideAction(InputResolveAction):
    """Action for reporting input from the user."""

    value: str
    result: InputResult | None


class InputResolveEvent(BaseEvent):
    """Base class for resolving input demands."""

    id: str


class InputCancelEvent(InputResolveEvent):
    """Event for cancelling an input demand."""


class InputProvideEvent(InputResolveEvent):
    """Event for reporting input from the user."""

    value: str
    result: InputResult | None
