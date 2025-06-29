"""Type definitions for the Redux store operations."""

from __future__ import annotations

import uuid
from dataclasses import field
from enum import StrEnum, auto
from typing import TYPE_CHECKING

from immutable import Immutable
from redux import BaseAction, BaseEvent

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ubo_app.store.services.file_system import PathSelectorConfig
    from ubo_app.store.services.speech_synthesis import ReadableInformation


class InputMethod(StrEnum):
    """Input method."""

    CAMERA = auto()
    WEB_DASHBOARD = auto()
    PATH_SELECTOR = auto()


class InputResult(Immutable):
    """Input result."""

    data: Mapping[str, str]
    files: dict[str, bytes]
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


class InputFieldDescription(Immutable):
    """Description of an input field in an input demand."""

    name: str
    label: str
    type: InputFieldType
    description: str | None = None
    title: str | None = None
    file_mimetype: str | None = None
    pattern: str | None = None
    default_value: str | None = None
    options: list[str] | None = None
    required: bool = False


class InputDescription(Immutable):
    """Description of an input demand."""

    input_method: InputMethod

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str | None = None
    prompt: str | None = None


class WebUIInputDescription(InputDescription):
    """Description of a web UI input field."""

    input_method: InputMethod = InputMethod.WEB_DASHBOARD

    fields: Sequence[InputFieldDescription] | None = None


class QRCodeInputDescription(InputDescription):
    """Description of a QR code input field."""

    input_method: InputMethod = InputMethod.CAMERA

    instructions: ReadableInformation | None = None
    pattern: str | None = None


class PathInputDescription(InputDescription):
    """Description of a QR code input field."""

    input_method: InputMethod = InputMethod.PATH_SELECTOR

    selector_config: PathSelectorConfig


class InputAction(BaseAction):
    """Base class for input actions."""


class InputDemandAction(InputAction):
    """Action for demanding input from the user."""

    description: InputDescription


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
