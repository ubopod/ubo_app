"""Docker store types."""

from __future__ import annotations

import functools
from dataclasses import field
from enum import StrEnum, auto

from immutable import Immutable
from redux import BaseAction, BaseCombineReducerState, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store


class DockerStatus(StrEnum):
    """Docker status."""

    UNKNOWN = auto()
    NOT_INSTALLED = auto()
    INSTALLING = auto()
    NOT_RUNNING = auto()
    RUNNING = auto()
    ERROR = auto()


class ImageStatus(StrEnum):
    """Image status."""

    NOT_AVAILABLE = auto()
    FETCHING = auto()
    AVAILABLE = auto()
    CREATED = auto()
    RUNNING = auto()
    ERROR = auto()


class DockerAction(BaseAction):
    """Docker action."""


class DockerSetStatusAction(DockerAction):
    """Set status of docker service."""

    status: DockerStatus


class DockerStoreUsernameAction(DockerAction):
    """Store username for a registry."""

    registry: str
    username: str


class DockerRemoveUsernameAction(DockerAction):
    """Remove a registry for stored usernames."""

    registry: str


class DockerImageAction(DockerAction):
    """Docker image action."""

    image: str


class DockerImageSetStatusAction(DockerImageAction):
    """Docker image set status action."""

    status: ImageStatus
    ports: list[str] | None = None
    ip: str | None = None


class DockerImageSetDockerIdAction(DockerImageAction):
    """Docker image set docker id action."""

    docker_id: str


class DockerEvent(BaseEvent):
    """Docker event."""


class DockerServiceState(Immutable):
    """Docker service state."""

    status: DockerStatus = DockerStatus.UNKNOWN
    usernames: dict[str, str] = field(
        default_factory=functools.partial(
            read_from_persistent_store,
            'docker_usernames',
            object_type=dict[str, str],
        ),
    )


class DockerImageEvent(DockerEvent):
    """Docker image event."""

    image: str


class DockerImageRegisterAppEvent(DockerImageEvent):
    """Register image entry in apps in store."""


class ImageState(Immutable):
    """Image state."""

    id: str
    status: ImageStatus = ImageStatus.NOT_AVAILABLE
    container_ip: str | None = None
    docker_id: str | None = None
    ports: list[str] = field(default_factory=list)

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
