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
    STARTING = auto()
    RUNNING = auto()
    ERROR = auto()
    PROCESSING = auto()


class DockerItemHealth(StrEnum):
    """How an app is faring, as distinct from where it is in its lifecycle.

    Kept out of ``DockerItemStatus`` on purpose. That enum drives control flow
    all over the service — ``is_available``, the rebind gate, the broker
    recreation set, the Zigbee heal — through hardcoded tuples that a new member
    would silently fall out of, disabling exactly the recovery paths a crashed
    app needs.
    """

    OK = auto()
    # Came back on its own after one or more policy-driven restarts.
    RECOVERED = auto()
    # Restarting repeatedly and recently: it cannot stay up.
    CRASH_LOOPING = auto()


# A container that restarted once an hour ago has recovered; one that restarted
# three times in the last five minutes has not. `restart_count` is cumulative
# since the last manual start, so recency has to be part of the test.
CRASH_LOOP_THRESHOLD = 3
CRASH_LOOP_WINDOW = 300.0


class DockerAppStatus(Immutable):
    """Serializable projection of one app's state, for non-menu surfaces.

    `state.docker` itself cannot be streamed to a client: `combine_reducers`
    synthesizes a per-image attribute on `DockerState` at runtime, and none of
    those exist in the proto message — serializing the slice raises `KeyError`
    and takes down the whole `SubscribeStore` stream, every selector in it, not
    just this one. This lives on `DockerServiceState`, which is a plain
    `Immutable` and does serialize.

    `label` and `icon` are copied in because they live Python-side in the
    `IMAGES` registry's `ContainerEntry`, not in `ImageState`.
    """

    id: str
    label: str
    icon: str
    status: DockerItemStatus = DockerItemStatus.NOT_AVAILABLE
    # Carried alongside the lifecycle status rather than folded into it, so a
    # consumer can apply the same precedence the Apps menu tint does: health
    # outranks status, because with `restart_policy: always` a failing app is
    # back to RUNNING seconds after it died.
    health: DockerItemHealth = DockerItemHealth.OK


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


class DockerImageSetExposeToLanAction(DockerAction):
    """Set whether an app's published ports bind to the LAN (0.0.0.0).

    When ``False`` the app's ports bind to loopback (``127.0.0.1``) only. The
    flag is keyed by image id and lives in ``DockerServiceState`` so it can be
    persisted alongside the other service-level settings.
    """

    image: str
    expose_to_lan: bool


class DockerSetZigbeeIntentAction(DockerAction):
    """Set the desired Zigbee USB coordinator passthrough into Home Assistant.

    Persists *intent* (whether passthrough is wanted, and which adapter by its
    stable ``/dev/serial/by-id`` symlink), never a compose line. The compose
    ``devices:`` mapping is re-derived from this intent at render time so a
    stale mapping to an unplugged dongle can't brick HA on an unattended start.
    """

    enabled: bool
    adapter_by_id: str = ''


class DockerSetHostNetworkAction(DockerAction):
    """Set whether Home Assistant runs on the host's network stack.

    Host networking is what makes HA's mDNS/SSDP discovery work: the container
    shares the host's interfaces, so multicast reaches the LAN. It is the only
    option that works over Wi-Fi — a macvlan sub-interface has its own MAC, and
    an access point only accepts one MAC per associated station, so its frames
    are silently dropped. Intent only; the compose ``network_mode`` and the
    hostname shims that keep the add-on bus reachable are derived at render.
    """

    enabled: bool


class DockerSetAppStatusAction(DockerAction):
    """Record an app's projected status in ``DockerServiceState.apps``.

    Deliberately not a ``DockerImageAction``: those are routed to the per-image
    reducer by ``image`` id, and this writes the service slice instead. An app
    reported as ``NOT_AVAILABLE`` is evicted rather than stored — see the
    reducer.
    """

    app: DockerAppStatus


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


class DockerImageReportExitAction(DockerImageAction):
    """Record how an app's container last exited, as the daemon reports it.

    Latched rather than folded into ``status``: every container is created with
    ``restart_policy: always``, so a crash is followed by a restart within
    seconds and any status derived from it would be gone before it was read.
    """

    restart_count: int
    exit_code: int | None = None
    exit_at: float | None = None
    error: str = ''
    # Compositions only. `RestartCount` is per-container and `compose ps` does
    # not report it, so a stack says which of its services cannot stay up
    # instead. Always sent, so a recovered stack clears it.
    failing_services: tuple[str, ...] = ()


class DockerImageUpdateMetadataAction(DockerImageAction):
    """Update image metadata (e.g., instructions)."""

    instructions: str | None = None


class DockerImageFetchAction(DockerImageAction):
    """Fetch image or composition."""


class DockerImageRemoveAction(DockerImageAction):
    """Remove image or composition."""


class DockerImageRunAction(DockerImageAction):
    """Run container or composition."""


class DockerImageStopAction(DockerImageAction):
    """Stop container or composition."""


class DockerImageReleaseAction(DockerImageAction):
    """Release composition resources (stop + cleanup)."""


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
            output_type=dict[str, str],
        ),
    )
    # Per-app LAN exposure, keyed by image id. Missing/``False`` means the
    # app's published ports bind to loopback only. Only apps that opt into the
    # toggle (``ContainerEntry.supports_lan_toggle``) consult this map.
    expose_to_lan: dict[str, bool] = field(
        default_factory=functools.partial(
            read_from_persistent_store,
            'docker_expose_to_lan',
            output_type=dict[str, bool],
        ),
    )
    # Desired Zigbee USB coordinator passthrough into Home Assistant's ZHA.
    # Intent only — the compose `devices:` mapping is re-derived from this at
    # render time against the live `/dev/serial/by-id` enumeration.
    zigbee_enabled: bool = field(
        default_factory=functools.partial(
            read_from_persistent_store,
            'docker_zigbee_enabled',
            default=False,
            output_type=bool,
        ),
    )
    zigbee_adapter_by_id: str = field(
        default_factory=functools.partial(
            read_from_persistent_store,
            'docker_zigbee_adapter_by_id',
            default='',
            output_type=str,
        ),
    )
    # Per-app status for surfaces that render from the store rather than from
    # the menu (the web UI dashboard). Only apps whose image is actually on the
    # device appear — the reducer evicts an app that goes `NOT_AVAILABLE`.
    #
    # Derived, and deliberately *not* persisted like its siblings above: a
    # restored entry would outlive its container and claim an app was running
    # before docker had reconciled anything.
    apps: dict[str, DockerAppStatus] = field(default_factory=dict)
    # Whether Home Assistant runs on the host's network stack (for mDNS/SSDP
    # discovery). Intent only — the compose `network_mode` and the hostname
    # shims that keep the add-on bus reachable are derived at render time.
    host_network_enabled: bool = field(
        default_factory=functools.partial(
            read_from_persistent_store,
            'docker_host_network_enabled',
            default=False,
            output_type=bool,
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


class DockerImageRebindEvent(DockerImageEvent):
    """Re-apply an app's port binding (recreate/restart so it takes effect)."""


class ImageState(Immutable):
    """Image state."""

    id: str
    label: str
    instructions: str | None
    status: DockerItemStatus = DockerItemStatus.NOT_AVAILABLE
    container_ip: str | None = None
    docker_id: str | None = None
    ports: list[str] = field(default_factory=list)
    # How the container last exited, as the daemon reports it. Deliberately
    # separate from `status`: with `restart_policy: always` a crash is undone by
    # a restart within seconds, so a status carrying it would never be seen.
    # `restart_count` is the daemon's own — it counts policy-driven restarts and
    # resets on a manual start, which is what distinguishes a crash from a stop.
    restart_count: int = 0
    last_exit_code: int | None = None
    last_exit_at: float | None = None
    last_error: str = ''
    # Compositions only: the services in the stack that cannot stay up.
    failing_services: tuple[str, ...] = ()

    @property
    def is_fetching(self: ImageState) -> bool:
        """Check if image is available."""
        return self.status == DockerItemStatus.FETCHING

    @property
    def is_available(self: ImageState) -> bool:
        """Check if image is available."""
        return self.status in [
            DockerItemStatus.AVAILABLE,
            DockerItemStatus.STARTING,
            DockerItemStatus.RUNNING,
        ]

    @property
    def is_running(self: ImageState) -> bool:
        """Check if image is running."""
        return self.status == DockerItemStatus.RUNNING


def derive_health(image: ImageState, *, now: float) -> DockerItemHealth:
    """Classify an app's health from what the daemon last reported.

    Keyed on ``restart_count`` rather than the exit code, because the exit code
    cannot tell the two cases apart: ``container.stop()`` is SIGTERM then
    SIGKILL, so a perfectly deliberate stop exits 143 or 137. Only the restart
    policy increments this counter, and a manual start resets it — so a nonzero
    count means the daemon revived something the user did not stop.
    """
    # An app that is not meant to be up is not unhealthy, it is off. Its crash
    # history stops being actionable the moment the user stops or removes it,
    # and `docker stop` does not reset `RestartCount` — only `docker start`
    # does — so without this the count would outlive the thing it described.
    if image.status not in (DockerItemStatus.STARTING, DockerItemStatus.RUNNING):
        return DockerItemHealth.OK

    # A stack reports by name instead of by count, since `compose ps` has no
    # per-container restart counter to read.
    if image.failing_services:
        return DockerItemHealth.CRASH_LOOPING
    if image.restart_count <= 0:
        return DockerItemHealth.OK
    if (
        image.restart_count >= CRASH_LOOP_THRESHOLD
        and image.last_exit_at is not None
        and now - image.last_exit_at < CRASH_LOOP_WINDOW
    ):
        return DockerItemHealth.CRASH_LOOPING
    return DockerItemHealth.RECOVERED


class DockerState(BaseCombineReducerState):
    """Docker state."""

    service: DockerServiceState

    def __getattribute__(self: DockerState, name: str) -> ImageState:
        """Set type for random attributes of DockerState."""
        return super().__getattribute__(name)
