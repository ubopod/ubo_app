"""Docker store types."""
from __future__ import annotations

from enum import Enum, auto

from redux import BaseAction, BaseCombineReducerState, BaseEvent, Immutable


class DockerStatus(Enum):
    """Docker status."""

    UNKNOWN = auto()
    NOT_INSTALLED = auto()
    INSTALLING = auto()
    NOT_RUNNING = auto()
    RUNNING = auto()
    ERROR = auto()


class ImageStatus(Enum):
    """Image status."""

    NOT_AVAILABLE = auto()
    FETCHING = auto()
    AVAILABLE = auto()
    RUNNING = auto()
    ERROR = auto()


class DockerAction(BaseAction):
    """Docker action."""


class DockerSetStatusAction(DockerAction):
    """Docker set status action."""

    status: DockerStatus


class DockerImageAction(DockerAction):
    """Docker image action."""

    image: str


class DockerImageSetStatusAction(DockerImageAction):
    """Docker image action."""

    status: ImageStatus


class DockerEvent(BaseEvent):
    """Docker event."""


class DockerServiceState(Immutable):
    """Docker service state."""

    status: DockerStatus = DockerStatus.UNKNOWN


class DockerImageEvent(DockerEvent):
    """Docker image event."""

    image: str


class ImageState(Immutable):
    """Image state."""

    id: str
    label: str
    icon: str
    path: str
    status: ImageStatus = ImageStatus.NOT_AVAILABLE

    @property
    def is_fetching(self: ImageState) -> bool:
        """Check if image is available."""
        return self.status == ImageStatus.FETCHING

    @property
    def is_available(self: ImageState) -> bool:
        """Check if image is available."""
        return self.status in [ImageStatus.AVAILABLE, ImageStatus.RUNNING]

    @property
    def is_running(self: ImageState) -> bool:
        """Check if image is running."""
        return self.status == ImageStatus.RUNNING


class DockerState(BaseCombineReducerState):
    """Docker state."""

    service: DockerServiceState

    def __getattribute__(self: DockerState, name: str) -> ImageState:
        """Set type for random attributes of DockerState."""
        return super().__getattribute__(name)
