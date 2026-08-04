"""Store types for the MQTT bridge service.

The bridge is the pod's single connection to an MQTT broker. Other services do
not talk to it directly — services are not importable across each other — they
dispatch :class:`MqttPublishAction` with a *relative* channel and the bridge
prefixes its own ``ubo/<pod-id>/`` namespace.

Home Assistant entities are declared with :class:`MqttComponent`, which is
deliberately spelled in Home Assistant's own vocabulary rather than any
service's private one, so a producer can describe its entities without the
bridge knowing anything about that producer's state shape. They reach the
bridge through the contribution registry at the bottom of this module.
"""

# ruff: noqa: D101
from __future__ import annotations

import json
from dataclasses import field
from enum import StrEnum, auto
from typing import Any

from immutable import Immutable
from redux import BaseAction, BaseEvent

from ubo_app.utils.persistent_store import read_from_persistent_store

BROKER_PERSISTENT_KEY = 'mqtt:broker'
IS_ENABLED_PERSISTENT_KEY = 'mqtt:is_enabled'
ALLOW_REMOTE_CONTROL_PERSISTENT_KEY = 'mqtt:allow_remote_control'
PUBLISHED_COMPONENTS_PERSISTENT_KEY = 'mqtt:published_components'
BUNDLED_EXPOSE_TO_LAN_PERSISTENT_KEY = 'mqtt:bundled_expose_to_lan'
BUNDLED_CREDENTIALS_REVISION_PERSISTENT_KEY = 'mqtt:bundled_credentials_revision'

# The bundled broker's address. Lives here rather than in the service so the
# field defaults, the parser's fallbacks and the bundled-source forcing below
# all share one literal.
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 1883
DEFAULT_TLS_PORT = 8883

MIN_PORT = 1
MAX_PORT = 65535

# Inbound commands live under their own segment of the pod's namespace, so
# subscribing to them does not also subscribe to everything the pod publishes.
# Here rather than in the bridge because a contributing service has to name the
# same channel when it declares a commandable entity, and services cannot
# import each other.
COMMAND_SEGMENT = 'command'

# The bundled broker authenticates every connection — there is no anonymous
# listener. The docker service generates this credential the first time it
# renders the Mosquitto config; the bridge presents it whenever the broker
# source is ``BUNDLED``, and the MQTT settings menu can replace it so the same
# credentials can be handed to Home Assistant or any other client. Here because
# the two services cannot import each other.
BUNDLED_BROKER_USERNAME = 'ubo'
BUNDLED_BROKER_PASSWORD_SECRET_ID = 'MQTT_BUNDLED_BROKER_PASSWORD'  # noqa: S105


class MqttAction(BaseAction): ...


class MqttEvent(BaseEvent): ...


class MqttConnectionStatus(StrEnum):
    DISABLED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


class MqttBrokerSource(StrEnum):
    """Which broker the bridge should target.

    ``BUNDLED`` is the Mosquitto container shipped inside the Home Assistant
    composition, published on the host's loopback (or, when
    ``bundled_expose_to_lan`` is set, on every interface).
    """

    BUNDLED = auto()
    EXTERNAL = auto()


class MqttBrokerConfig(Immutable):
    source: MqttBrokerSource = MqttBrokerSource.BUNDLED
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    username: str = ''
    # The password itself lives in the secrets file, never in the store.
    has_password: bool = False
    use_tls: bool = False
    ca_cert_path: str = ''


class MqttComponent(Immutable):
    """One Home Assistant entity, described in Home Assistant's vocabulary.

    ``state_channel`` and ``command_channel`` are *relative* — the bridge owns
    the ``ubo/<pod-id>/`` prefix — so a producer never needs to know the pod's
    identity to describe its entities.
    """

    component_id: str
    platform: str
    name: str
    state_channel: str | None = None
    value_template: str | None = None
    command_channel: str | None = None
    payload_press: str | None = None
    device_class: str | None = None
    unit_of_measurement: str | None = None
    state_class: str | None = None
    suggested_display_precision: int | None = None
    event_types: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    expire_after: int | None = None
    command_template: str | None = None
    # `min_value`/`max_value` rather than `min`/`max`: those names shadow the
    # builtins and ruff rejects them. They render to Home Assistant's
    # unabbreviated `min`/`max` keys. Declaring them is not optional for a
    # `number` — its defaults are 1..100 step 1, so an unset 0..1 brightness
    # would render as a 1-100 integer slider.
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    mode: str | None = None
    # Nullable so they are omitted for entities that do not care — otherwise
    # every sensor payload would carry a meaningless `ret: false`. Only
    # meaningful on a command topic, where `retain` must stay False: a retained
    # command replays on every reconnect.
    retain: bool | None = None
    qos: int | None = None


def _parse_opt_in(value: object) -> bool:
    """Read a persisted boolean strictly — anything but `True` is off.

    `read_from_persistent_store` hands back whatever JSON held, and a string is
    truthy: a hand-edited `"false"` would *enable* remote control on every
    subsequent check. A security-sensitive flag has to fail closed.
    """
    return value is True


def _parse_revision(value: object) -> int:
    """Read the credentials revision, treating anything unusable as zero."""
    try:
        return max(0, int(value))  # pyright: ignore [reportArgumentType]
    except (TypeError, ValueError):
        return 0


def _parse_port(value: object) -> int:
    """Read a port, falling back to the default for anything unusable."""
    try:
        port = int(value)  # pyright: ignore [reportArgumentType]
    except (TypeError, ValueError):
        return DEFAULT_PORT
    return port if MIN_PORT <= port <= MAX_PORT else DEFAULT_PORT


def _parse_broker(value: object) -> MqttBrokerConfig:
    """Rebuild the broker config from the persistent store.

    Defensive in a way the rest of the store deliberately is not, because this
    runs at *class-definition* time via `MqttState`'s default factory: an
    exception here is not a bad config, it is an import-time crash that takes
    the whole app down. A hand-edited or truncated ``state.json`` must degrade
    to the defaults instead.
    """
    try:
        raw = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return MqttBrokerConfig()
    if not isinstance(raw, dict):
        return MqttBrokerConfig()

    source = raw.get('source')
    if source not in tuple(MqttBrokerSource):
        return MqttBrokerConfig()

    # The bundled broker is the loopback-published Mosquitto in the Home
    # Assistant composition — it is that address by definition. Rebuilding it
    # from defaults rather than trusting the stored fields means a config left
    # over from an external broker cannot make a "bundled" broker point at an
    # arbitrary host.
    if source == MqttBrokerSource.BUNDLED:
        return MqttBrokerConfig()

    return MqttBrokerConfig(
        source=MqttBrokerSource.EXTERNAL,
        host=str(raw.get('host', DEFAULT_HOST)),
        port=_parse_port(raw.get('port', DEFAULT_PORT)),
        username=str(raw.get('username', '')),
        has_password=bool(raw.get('has_password', False)),
        use_tls=bool(raw.get('use_tls', False)),
        ca_cert_path=str(raw.get('ca_cert_path', '')),
    )


class MqttSetStatusAction(MqttAction):
    status: MqttConnectionStatus
    error: str | None = None


class MqttSetBrokerAction(MqttAction):
    broker: MqttBrokerConfig


class MqttSetEnabledAction(MqttAction):
    is_enabled: bool


class MqttSetBundledExposeToLanAction(MqttAction):
    """Bind the bundled broker's published port to the LAN, or to loopback."""

    expose_to_lan: bool


class MqttBundledCredentialsChangedAction(MqttAction):
    """Signal that the bundled broker's password in the secrets file changed.

    Carries no value — the password is never in the store. It exists so the
    docker service can observe a transition and re-render the broker's
    `password_file`, which a secrets-only write would otherwise not trigger.
    """


class MqttSetAllowRemoteControlAction(MqttAction):
    allow_remote_control: bool


class MqttSetPublishedComponentsAction(MqttAction):
    """Record what the last discovery announce declared.

    Persisted so a component removed while the pod was switched off is still
    retired afterwards. Discovery is a *retained* message: Home Assistant holds
    the previous payload across a restart, so an entity that merely stops being
    mentioned stays on the dashboard forever.
    """

    published_components: dict[str, str]


class MqttPublishAction(MqttAction):
    """Publish `payload` on a channel relative to this pod's namespace.

    The reducer is transparent to this action — it only re-emits it as
    :class:`MqttPublishEvent` for the bridge to pick up, leaving state
    untouched.
    """

    channel: str
    payload: str
    retain: bool = False
    qos: int = 0


class MqttPublishEvent(MqttEvent):
    channel: str
    payload: str
    retain: bool = False
    qos: int = 0


class MqttRequestAnnounceAction(MqttAction):
    """Ask the bridge to rebuild and republish the discovery payload.

    Dispatched by any contributor whose entity set changed, and by the bridge
    itself when Home Assistant announces it has come back.
    """


class MqttAnnounceRequestedEvent(MqttEvent): ...


class MqttState(Immutable):
    status: MqttConnectionStatus = MqttConnectionStatus.DISABLED
    broker: MqttBrokerConfig = field(
        default_factory=lambda: read_from_persistent_store(
            BROKER_PERSISTENT_KEY,
            default=MqttBrokerConfig(),
            mapper=_parse_broker,
        ),
    )
    is_enabled: bool = field(
        default=read_from_persistent_store(
            IS_ENABLED_PERSISTENT_KEY,
            default=True,
            mapper=_parse_opt_in,
        ),
    )
    # Master switch for inbound commands. Off by default and deliberately so:
    # a broker is only as trustworthy as the clients holding its credentials.
    # This is a user control, not an authentication boundary.
    allow_remote_control: bool = field(
        default=read_from_persistent_store(
            ALLOW_REMOTE_CONTROL_PERSISTENT_KEY,
            default=False,
            mapper=_parse_opt_in,
        ),
    )
    # Whether the bundled broker's published port binds all interfaces rather
    # than loopback. Safe to offer because that listener authenticates; it is
    # how a phone app or a second Home Assistant reaches this pod's broker.
    bundled_expose_to_lan: bool = field(
        default=read_from_persistent_store(
            BUNDLED_EXPOSE_TO_LAN_PERSISTENT_KEY,
            default=False,
            mapper=_parse_opt_in,
        ),
    )
    # Bumped whenever the bundled broker's password changes. The password lives
    # in the secrets file, so a change is invisible to the store — and the
    # docker service needs *some* state transition to notice it must re-render
    # the broker's `password_file` and recreate the container.
    bundled_credentials_revision: int = field(
        default_factory=lambda: read_from_persistent_store(
            BUNDLED_CREDENTIALS_REVISION_PERSISTENT_KEY,
            default=0,
            mapper=_parse_revision,
        ),
    )
    last_error: str | None = None
    # Component id -> platform, as last announced. Persisted because discovery
    # is retained: without it, an entity removed while the pod was off is never
    # retired and lingers in Home Assistant.
    published_components: dict[str, str] = field(
        default_factory=lambda: read_from_persistent_store(
            PUBLISHED_COMPONENTS_PERSISTENT_KEY,
            default={},
            mapper=_parse_published_components,
        ),
    )


def _parse_published_components(value: object) -> dict[str, str]:
    """Rebuild the last announced component map, tolerating a bad document.

    Runs at class-definition time like `_parse_broker`, so a malformed entry
    must degrade rather than raise.
    """
    try:
        raw = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(platform)
        for key, platform in raw.items()
        if isinstance(key, str) and isinstance(platform, str)
    }


def persist_broker(broker: MqttBrokerConfig) -> str:
    """Render the broker config as the string the persistent store holds.

    Lives next to `_parse_broker` deliberately: the two are one contract, and a
    selector that handed the `Immutable` over directly would get a dill-pickled
    `_type` marker written instead of the plain JSON the parser reads back.
    """
    return json.dumps(serialize_broker(broker))


def serialize_broker(broker: MqttBrokerConfig) -> dict[str, Any]:
    """Render the broker config for the persistent store."""
    return {
        'source': str(broker.source),
        'host': broker.host,
        'port': broker.port,
        'username': broker.username,
        'has_password': broker.has_password,
        'use_tls': broker.use_tls,
        'ca_cert_path': broker.ca_cert_path,
    }
