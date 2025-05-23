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


class DockerItemStatus(StrEnum):
    """Image status."""

    NOT_AVAILABLE = auto()
    FETCHING = auto()
    AVAILABLE = auto()
    CREATED = auto()
    RUNNING = auto()
    ERROR = auto()
    PROCESSING = auto()


class DockerAction(BaseAction):
    """Docker action."""


class DockerInstallAction(DockerAction):
    """Install docker."""


class DockerStartAction(DockerAction):
    """Start docker service."""


class DockerStopAction(DockerAction):
    """Stop docker service."""


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

    status: DockerItemStatus
    ports: list[str] | None = None
    ip: str | None = None


class DockerImageSetDockerIdAction(DockerImageAction):
    """Docker image set docker id action."""

    docker_id: str


class DockerImageFetchCompositionAction(DockerImageAction):
    """Fetch composition."""


class DockerImageFetchAction(DockerImageAction):
    """Fetch image."""


class DockerImageRemoveCompositionAction(DockerImageAction):
    """Remove composition."""


class DockerImageRemoveAction(DockerImageAction):
    """Remove image."""


class DockerImageRunCompositionAction(DockerImageAction):
    """Run composition."""


class DockerImageRunContainerAction(DockerImageAction):
    """Run container."""


class DockerImageStopCompositionAction(DockerImageAction):
    """Stop composition."""


class DockerImageStopContainerAction(DockerImageAction):
    """Stop container."""


class DockerImageReleaseCompositionAction(DockerImageAction):
    """Release composition."""


class DockerImageRemoveContainerAction(DockerImageAction):
    """Remove container."""


class DockerEvent(BaseEvent):
    """Docker event."""


class DockerInstallEvent(DockerEvent):
    """Signal for installing docker."""


class DockerStartEvent(DockerEvent):
    """Signal for starting docker service."""


class DockerStopEvent(DockerEvent):
    """Signal for stopping docker service."""


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


class DockerImageFetchCompositionEvent(DockerImageEvent):
    """Fetch composition."""


class DockerImageFetchEvent(DockerImageEvent):
    """Fetch image."""


class DockerImageRemoveCompositionEvent(DockerImageEvent):
    """Remove composition."""


class DockerImageRemoveEvent(DockerImageEvent):
    """Remove image."""


class DockerImageRunCompositionEvent(DockerImageEvent):
    """Run composition."""


class DockerImageRunContainerEvent(DockerImageEvent):
    """Run container."""


class DockerImageStopCompositionEvent(DockerImageEvent):
    """Stop composition."""


class DockerImageStopContainerEvent(DockerImageEvent):
    """Stop container."""


class DockerImageReleaseCompositionEvent(DockerImageEvent):
    """Release composition."""


class DockerImageRemoveContainerEvent(DockerImageEvent):
    """Remove container."""


class ImageState(Immutable):
    """Image state."""

    id: str
    label: str
    instructions: str | None
    status: DockerItemStatus = DockerItemStatus.NOT_AVAILABLE
    container_ip: str | None = None
    docker_id: str | None = None
    ports: list[str] = field(default_factory=list)

    @property
    def is_fetching(self: ImageState) -> bool:
        """Check if image is available."""
        return self.status == DockerItemStatus.FETCHING

    @property
    def is_available(self: ImageState) -> bool:
        """Check if image is available."""
        return self.status in [DockerItemStatus.AVAILABLE, DockerItemStatus.RUNNING]

    @property
    def is_running(self: ImageState) -> bool:
        """Check if image is running."""
        return self.status == DockerItemStatus.RUNNING


class DockerState(BaseCombineReducerState):
    """Docker state."""

    service: DockerServiceState

    def __getattribute__(self: DockerState, name: str) -> ImageState:
        """Set type for random attributes of DockerState."""
        return super().__getattribute__(name)
