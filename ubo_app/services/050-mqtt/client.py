"""Hold one broker session open and pump the pod's traffic through it.

The only module that knows `aiomqtt` exists. Everything decision-shaped lives
in the pure `topics`/`discovery` modules so it can be tested without a broker.

The broker is, by default, the Mosquitto container bundled with the Home
Assistant composition and published on the host's loopback. Publishing is
therefore gated on Home Assistant actually running — without it there is no
broker to talk to.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import aiomqtt
import commands
from constants import (
    BIRTH_DEBOUNCE_INTERVAL,
    HA_STATUS_TOPIC,
    HOME_ASSISTANT_COMPOSITION_ID,
    LOOPBACK_HOSTS,
    MAX_OUTBOUND_PAYLOAD,
    MAX_TOPIC_BYTES,
    MQTT_PASSWORD_SECRET_ID,
    OUTBOUND_OVERFLOW_LOG_INTERVAL,
    OUTBOUND_QUEUE_SIZE,
    PROBE_TIMEOUT,
    RECONNECT_MAX,
    RECONNECT_MIN,
)
from discovery import build_discovery_payload, component_platforms
from task_scope import TaskScope
from topics import (
    availability_topic,
    channel_topic,
    command_subscription,
    device_serial,
    discovery_topic,
    is_relative,
    parse_command_name,
)

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.docker import DockerItemStatus
from ubo_app.store.services.mqtt import (
    BUNDLED_BROKER_PASSWORD_SECRET_ID,
    BUNDLED_BROKER_USERNAME,
    COMMAND_SEGMENT,
    MqttBrokerSource,
    MqttConnectionStatus,
    MqttSetPublishedComponentsAction,
    MqttSetStatusAction,
)
from ubo_app.utils.error_handlers import report_service_error
from ubo_app.utils.mqtt_registry import (
    get_mqtt_components,
)
from ubo_app.utils.secrets import read_secret

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from ubo_app.store.services.mqtt import (
        MqttBrokerConfig,
        MqttComponent,
        MqttPublishEvent,
        MqttState,
    )

_queue: asyncio.Queue[MqttPublishEvent] | None = None
_announce_event: asyncio.Event | None = None
_settings_changed: asyncio.Event | None = None
_last_overflow_log = 0.0


@dataclass
class BridgeState:
    """What `bridge_task` owns and lends to each session.

    `published` — component id to platform, as last announced — is what lets an
    entity that disappeared while the bridge was down still be retired. The
    queue is *not* a cross-reconnect buffer: it is opened only for the duration
    of a session, because replaying stale telemetry and events is worse than
    losing it.
    """

    # Only accepts work while a session is live; see `_accept_publishes`.
    queue: asyncio.Queue[MqttPublishEvent]
    announce_event: asyncio.Event
    end_event: asyncio.Event
    # Set whenever the user changes a setting the live session was built from.
    # Ends the session cleanly so the supervisor re-reads the config at once
    # instead of waiting for the connection to happen to fail.
    settings_changed: asyncio.Event = field(default_factory=asyncio.Event)
    published: dict[str, str] = field(default_factory=dict)
    # `loop.time()` of the last handled Home Assistant birth; see
    # `_handle_home_assistant_birth`.
    last_birth: float | None = None
    # Owns every task a session spawns, so none of them outlive the service.
    scope: TaskScope = field(default_factory=lambda: TaskScope('mqtt:session'))


class ConnectionTarget:
    """Everything needed to open one broker session."""

    def __init__(
        self,
        broker: MqttBrokerConfig,
        password: str | None,
        *,
        username: str | None = None,
    ) -> None:
        """Capture the resolved broker settings."""
        self.host = broker.host
        self.port = broker.port
        self.username = username or broker.username or None
        self.password = password
        self.use_tls = broker.use_tls
        self.ca_cert_path = broker.ca_cert_path or None
        self.source = broker.source

    @property
    def is_loopback(self) -> bool:
        """Whether this target is the pod's own bundled broker."""
        return self.host in LOOPBACK_HOSTS


# `read_secret` is a synchronous dotenv file read and `_resolve_target` runs on
# every pass of the supervisor loop — every 5 s forever while idle — so
# passwords are cached here and invalidated when the settings change.
_password_cache: dict[str, str] = {}


def _read_password(secret_id: str, *, force: bool) -> str | None:
    """Return a stored broker password, re-reading the file only when needed.

    `force` bypasses the cache: it is the "Test Connection" path, which must see
    a just-edited secrets file even before the settings autorun has fired.

    A missing secret is deliberately not cached: for the bundled broker it
    means the Home Assistant composition has not generated the credential yet,
    and its later appearance must be picked up without a settings change.
    """
    if not force and secret_id in _password_cache:
        return _password_cache[secret_id]
    value = read_secret(secret_id)
    if value is not None:
        _password_cache[secret_id] = value
    else:
        _password_cache.pop(secret_id, None)
    return value


@store.with_state(lambda state: state.mqtt)
def _resolve_target(
    mqtt_state: MqttState,
    *,
    force: bool = False,
) -> ConnectionTarget | None:
    """Resolve the configured broker, or None when the bridge is switched off.

    `force` ignores the enabled flag, so "Test Connection" can answer while the
    bridge is off — which is precisely when someone is trying to work out why it
    is not connecting.
    """
    if not (mqtt_state.is_enabled or force):
        return None
    broker = mqtt_state.broker
    if broker.source == MqttBrokerSource.BUNDLED:
        # The bundled broker's host-loopback listener is authenticated with a
        # credential the docker service generates when it renders the
        # composition (see `MOSQUITTO_CONF` in the Home Assistant app).
        return ConnectionTarget(
            broker,
            _read_password(BUNDLED_BROKER_PASSWORD_SECRET_ID, force=force),
            username=BUNDLED_BROKER_USERNAME,
        )
    password = (
        _read_password(MQTT_PASSWORD_SECRET_ID, force=force)
        if broker.has_password
        else None
    )
    return ConnectionTarget(broker, password)


@store.with_state(lambda state: getattr(state, 'docker', None))
def _is_home_assistant_up(docker_state: object) -> bool:
    """Whether the composition hosting the bundled broker is running.

    Read straight off the docker slice rather than importing the docker service
    — services are not importable across each other, but store slices are. The
    slice itself may be missing (the docker service can be disabled), and
    `state.docker` *raises* then, so the selector guards with `getattr` and a
    missing slice reads as "not running".
    """
    home_assistant = getattr(docker_state, HOME_ASSISTANT_COMPOSITION_ID, None)
    return home_assistant is not None and home_assistant.status in (
        DockerItemStatus.STARTING,
        DockerItemStatus.RUNNING,
    )


@store.with_state(lambda state: state.mqtt.allow_remote_control)
def _is_remote_control_allowed(allow_remote_control: bool) -> bool:  # noqa: FBT001
    """Whether this session should subscribe to command topics at all."""
    return allow_remote_control


def _is_broker_reachable(target: ConnectionTarget) -> bool:
    """Whether it is worth attempting a connection at all.

    The bundled broker only exists while Home Assistant is up; an external one
    is always worth trying.
    """
    if target.source is MqttBrokerSource.EXTERNAL:
        return True
    return _is_home_assistant_up()


def _rejection(event: MqttPublishEvent) -> str | None:
    """Why this publish must not reach the broker, or None if it may.

    `MqttPublishEvent` is auto-enrolled into the gRPC surface, so every field
    here is caller-controlled. `_pump` hands them straight to Paho, which
    *raises* on a bad QoS or an oversized topic — and an exception there ends
    the session and starts the reconnect backoff. So the whole shape is checked
    before anything is queued, not just the channel.
    """
    if not is_relative(event.channel):
        return 'an absolute or wildcard channel'
    if event.channel.split('/', 1)[0] == COMMAND_SEGMENT:
        # The pod's own inbound namespace: a publish there would echo straight
        # back through `_route` and into the command table.
        return 'the inbound command namespace'
    if event.qos not in (0, 1, 2):
        return f'QoS {event.qos}'
    channel = event.channel.encode()
    if '\x00' in event.channel:
        return 'a null byte in the channel'
    if len(channel) > MAX_TOPIC_BYTES:
        return f'a {len(channel)}-byte channel'
    payload = len(event.payload.encode())
    if payload > MAX_OUTBOUND_PAYLOAD:
        return f'a {payload}-byte payload'
    return None


def enqueue(event: MqttPublishEvent) -> None:
    """Hand a publish request to the session. Dropped if nothing is connected.

    Overflow is deliberate — these are live telemetry ticks that the next one
    supersedes — but it is logged, at most once per interval, because a silently
    dropping queue is a debugging trap.
    """
    global _last_overflow_log  # noqa: PLW0603

    if _queue is None:
        return
    rejection = _rejection(event)
    if rejection is not None:
        logger.warning(
            'MQTT: refusing to publish',
            extra={'channel': event.channel, 'reason': rejection},
        )
        return
    try:
        _queue.put_nowait(event)
    except asyncio.QueueFull:
        now = time.monotonic()
        if now - _last_overflow_log > OUTBOUND_OVERFLOW_LOG_INTERVAL:
            _last_overflow_log = now
            logger.warning(
                'MQTT: outbound queue is full, dropping publishes',
                extra={'size': OUTBOUND_QUEUE_SIZE},
            )


def request_announce() -> None:
    """Ask the live session to rebuild and republish the discovery payload."""
    if _announce_event is not None:
        _announce_event.set()


def request_reconnect() -> None:
    """Tell the supervisor the settings it connected with have changed."""
    # The password may be among what changed; the next resolve re-reads it.
    _password_cache.clear()
    if _settings_changed is not None:
        _settings_changed.set()


@store.with_state(lambda state: state.mqtt.published_components)
def _last_published(published_components: dict[str, str]) -> dict[str, str]:
    """Return what the previous run told Home Assistant about."""
    return dict(published_components)


def _offerable(components: Sequence[MqttComponent]) -> list[MqttComponent]:
    """Drop every commandable entity while Home Assistant control is off.

    Enforced here, once, rather than trusted to each contributor: a button whose
    command topic nothing is subscribed to looks working and silently is not.
    Anything carrying a `command_channel` is by definition only useful when the
    bridge is listening, so this covers contributors that have not been written
    yet — the infrared buttons included.
    """
    if _is_remote_control_allowed():
        return list(components)
    return [
        component for component in components if component.command_channel is None
    ]


async def _publish_discovery(
    client: aiomqtt.Client,
    serial: str,
    published: dict[str, str],
) -> None:
    """(Re)announce the pod's entities, retiring any that have gone away."""
    components = _offerable(get_mqtt_components())
    current = component_platforms(components)
    removed = {
        component_id: platform
        for component_id, platform in published.items()
        if component_id not in current
    }

    payload = build_discovery_payload(
        serial,
        components,
        removed_components=removed,
    )
    await client.publish(
        discovery_topic(serial),
        json.dumps(payload),
        qos=1,
        retain=True,
    )

    published.clear()
    published.update(current)
    # Persisted, so a component removed while the pod is switched off is still
    # retired on the next boot.
    store.dispatch(
        MqttSetPublishedComponentsAction(published_components=dict(current)),
    )


async def _watch_announce_requests(
    client: aiomqtt.Client,
    serial: str,
    published: dict[str, str],
    announce_event: asyncio.Event,
) -> None:
    """Republish discovery whenever a contributor's entity set changes."""
    while True:
        await announce_event.wait()
        announce_event.clear()
        await _publish_discovery(client, serial, published)


async def _handle_home_assistant_birth(
    client: aiomqtt.Client,
    serial: str,
    bridge: BridgeState,
) -> None:
    """Republish discovery when Home Assistant restarts.

    Retained discovery survives a broker restart, but HA announces `online` on
    its own status topic when it comes back and expects integrations to
    re-announce.

    Debounced: `homeassistant/status` is broker-wide, so any peer can publish
    `online` to it repeatedly, and each birth costs a full discovery rebuild
    plus a retained republish.
    """
    now = asyncio.get_running_loop().time()
    if (
        bridge.last_birth is not None
        and now - bridge.last_birth < BIRTH_DEBOUNCE_INTERVAL
    ):
        logger.debug('MQTT: ignoring a repeated birth message')
        return
    bridge.last_birth = now
    logger.info('MQTT: Home Assistant came back, republishing discovery')
    await client.publish(availability_topic(serial), 'online', qos=1, retain=True)
    request_announce()


async def _handle_command(
    client: aiomqtt.Client,
    name: str,
    message: aiomqtt.Message,
) -> None:
    """Run one inbound command, refusing anything replayed by the broker."""
    if message.retain:
        # A retained command re-fires on every single reconnect. Nothing
        # legitimate publishes one — Home Assistant does not, and our own
        # discovery marks command topics `retain: false` — so drop it *and*
        # clear the slot, otherwise one poisoned message re-arms itself forever.
        logger.warning(
            'MQTT: ignoring a retained command',
            extra={'topic': str(message.topic)},
        )
        await client.publish(str(message.topic), b'', qos=0, retain=True)
        return

    payload = message.payload if isinstance(message.payload, bytes) else b''
    reason = commands.dispatch(name, payload)
    if reason is not None:
        logger.warning(
            'MQTT: refused a command',
            extra={'command': name, 'reason': reason},
        )


async def _route(
    client: aiomqtt.Client,
    serial: str,
    bridge: BridgeState,
    message: aiomqtt.Message,
) -> None:
    """Send one inbound message to whatever handles it."""
    topic = str(message.topic)
    if message.topic.matches(HA_STATUS_TOPIC):
        if message.payload == b'online':
            await _handle_home_assistant_birth(client, serial, bridge)
        return

    name = parse_command_name(serial, topic)
    if name is not None:
        await _handle_command(client, name, message)
        return

    logger.debug('MQTT: ignoring an unrouted message', extra={'topic': topic})


async def _dispatch_messages(
    client: aiomqtt.Client,
    serial: str,
    bridge: BridgeState,
) -> None:
    """Route every inbound message; the session's only message consumer.

    aiomqtt drains one shared queue behind `client.messages`, so a second
    `async for` over it would steal messages non-deterministically — every
    inbound concern has to be routed from here rather than growing its own loop.

    The `try` sits *inside* the loop on purpose: a malformed payload must not
    end the loop, and must not reach `bridge_task` and tear down the session.
    """
    async for message in client.messages:
        try:
            await _route(client, serial, bridge, message)
        except Exception:
            logger.exception(
                'MQTT: inbound handler failed',
                extra={'topic': str(message.topic)},
            )
            # Even the reporting is guarded: `report_service_error` resolves the
            # current service and dispatches, either of which can raise. An
            # exception from *here* would end the loop — the very thing this
            # handler exists to prevent.
            with contextlib.suppress(Exception):
                report_service_error()


def _drain(queue: asyncio.Queue[MqttPublishEvent]) -> None:
    """Throw away anything left in the outbound queue."""
    dropped = 0
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        dropped += 1
    if dropped:
        logger.warning('MQTT: dropped stale publishes', extra={'count': dropped})


@contextlib.contextmanager
def _accept_publishes(
    queue: asyncio.Queue[MqttPublishEvent],
) -> Iterator[None]:
    """Let producers enqueue, but only while a session is actually live.

    Outside this window `enqueue` drops on the floor. Buffering across a
    disconnect looks helpful and is not: the queue fills with the *oldest*
    events, discards every newer one, and then replays the stale ones when the
    broker comes back — an infrared event from an hour ago firing a Home
    Assistant automation.
    """
    global _queue  # noqa: PLW0603
    _queue = queue
    try:
        yield
    finally:
        _queue = None
        _drain(queue)


async def _pump(
    client: aiomqtt.Client,
    serial: str,
    queue: asyncio.Queue[MqttPublishEvent],
) -> None:
    """Forward each queued publish request to the broker."""
    while True:
        event = await queue.get()
        await client.publish(
            channel_topic(serial, event.channel),
            event.payload,
            qos=event.qos,
            retain=event.retain,
        )


async def _session(
    serial: str,
    target: ConnectionTarget,
    bridge: BridgeState,
) -> None:
    """Hold one broker session open until it fails or the service stops."""
    async with aiomqtt.Client(
        hostname=target.host,
        port=target.port,
        username=target.username,
        password=target.password,
        tls_params=aiomqtt.TLSParameters(ca_certs=target.ca_cert_path)
        if target.use_tls
        else None,
        will=aiomqtt.Will(
            availability_topic(serial),
            b'offline',
            qos=1,
            retain=True,
        ),
    ) as client:
        logger.info('MQTT: connected to the broker', extra={'host': target.host})
        store.dispatch(MqttSetStatusAction(status=MqttConnectionStatus.CONNECTED))

        # Anything a producer handed over between sessions is stale by now — a
        # reading has been superseded and an infrared event is long past. The
        # queue is only opened once the session is live (see `_accept_publishes`)
        # so this should be empty, but draining makes that explicit rather than
        # assumed.
        _drain(bridge.queue)

        # Availability before discovery, so Home Assistant never sees an entity
        # it believes is already offline.
        await client.publish(availability_topic(serial), 'online', qos=1, retain=True)
        await client.subscribe(HA_STATUS_TOPIC, qos=1)
        if _is_remote_control_allowed():
            # QoS 0: these are one-shot side effects, and QoS 1 redelivery would
            # mean an occasional duplicate chime or notification. Losing one is
            # the better failure. The subscription is torn down with the session
            # when the toggle flips, via the settings-changed event.
            await client.subscribe(command_subscription(serial), qos=0)
        await _publish_discovery(client, serial, bridge.published)

        # `report_errors=False`: the first exception is re-raised below and
        # reported by `bridge_task`, which also owns the backoff.
        tasks = [
            bridge.scope.create(
                _pump(client, serial, bridge.queue),
                name='mqtt:pump',
                report_errors=False,
            ),
            bridge.scope.create(
                _dispatch_messages(client, serial, bridge),
                name='mqtt:dispatch',
                report_errors=False,
            ),
            bridge.scope.create(
                _watch_announce_requests(
                    client,
                    serial,
                    bridge.published,
                    bridge.announce_event,
                ),
                name='mqtt:announce',
                report_errors=False,
            ),
            bridge.scope.create(
                bridge.end_event.wait(),
                name='mqtt:end',
                report_errors=False,
            ),
            bridge.scope.create(
                bridge.settings_changed.wait(),
                name='mqtt:settings',
                report_errors=False,
            ),
        ]
        try:
            with _accept_publishes(bridge.queue):
                done, _ = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        # `asyncio.wait` puts cancelled tasks in `done` too, and
        # `Task.exception()` *raises* `CancelledError` on one — and the scope
        # closing mid-wait (a service stop) is a clean exit, not a failure.
        failures = [
            task
            for task in done
            if not task.cancelled() and task.exception() is not None
        ]
        if not failures:
            # Leaving deliberately — the bridge was switched off, the broker was
            # changed, or the service is stopping. The Last Will only fires on an
            # ungraceful drop, so without this the broker keeps a retained
            # `online` for a pod that is no longer there.
            with contextlib.suppress(Exception):
                await client.publish(
                    availability_topic(serial),
                    b'offline',
                    qos=1,
                    retain=True,
                )
            return

        # A finished pump or watcher means the connection broke; re-raise so the
        # caller can back off and reconnect.
        raise failures[0].exception()  # pyright: ignore [reportGeneralTypeIssues]


async def probe() -> str | None:
    """Open a throwaway session against the configured broker.

    Returns `None` on success or a message to show the user. Deliberately
    independent of the live session — it touches neither the queue, the announce
    event nor `published` — so "Test Connection" says something useful even when
    the bridge is switched off or idling, which is exactly when a user is trying
    to work out why nothing is happening.
    """
    target = _resolve_target(force=True)
    if target is None:
        return 'No broker is configured.'

    try:
        async with asyncio.timeout(PROBE_TIMEOUT):
            async with aiomqtt.Client(
                hostname=target.host,
                port=target.port,
                username=target.username,
                password=target.password,
                tls_params=aiomqtt.TLSParameters(ca_certs=target.ca_cert_path)
                if target.use_tls
                else None,
            ):
                return None
    except TimeoutError:
        return f'{target.host}:{target.port} did not respond.'
    except aiomqtt.MqttError as exception:
        return str(exception) or 'The broker refused the connection.'
    except Exception:
        # The detail stays in the log only: this arm covers local failures like
        # an unreadable CA file, and echoing `str(exception)` back would make
        # "Test Connection" a file-existence oracle for any path ubo can read.
        logger.exception('MQTT: probe failed', extra={'host': target.host})
        return 'The connection failed unexpectedly; see the logs.'


async def _idle(bridge: BridgeState, seconds: float) -> None:
    """Wait out a retry, but wake early on a settings change or a stop.

    Plain `asyncio.sleep` here would mean a user who has just enabled the bridge
    or corrected a wrong password waits out the full backoff — up to a minute —
    before anything happens. The end event is raced for the same reason: a
    stopping service must not sit out the backoff either, or cleanup blows its
    grace period and the status is left stuck.
    """
    waiters = [
        asyncio.ensure_future(bridge.settings_changed.wait()),
        asyncio.ensure_future(bridge.end_event.wait()),
    ]
    try:
        await asyncio.wait(
            waiters,
            timeout=seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)


_scope: TaskScope | None = None


async def close_session_tasks() -> None:
    """Cancel anything the live session still has running."""
    if _scope is not None:
        await _scope.aclose()


async def bridge_task(end_event: asyncio.Event) -> None:
    """Keep a broker session up for as long as there is anything to publish.

    Publishing is pointless without a broker and without entities, so this idles
    until at least one service has contributed an entity *and* the configured
    broker looks reachable.
    """
    global _announce_event, _scope, _settings_changed  # noqa: PLW0603

    bridge = BridgeState(
        queue=asyncio.Queue(maxsize=OUTBOUND_QUEUE_SIZE),
        announce_event=asyncio.Event(),
        end_event=end_event,
        # Seeded from the persisted map so the first announce of this process
        # retires whatever went away while the pod was off.
        published=_last_published(),
    )
    # `_queue` is deliberately *not* set here — `_accept_publishes` opens it only
    # while a session is live, so a producer cannot fill it while disconnected.
    _announce_event = bridge.announce_event
    _settings_changed = bridge.settings_changed
    _scope = bridge.scope
    serial = ''
    backoff = RECONNECT_MIN
    # Only dispatched on a transition: the idle branch re-runs every 5 s
    # forever, and an identical status is not worth a full root-reducer pass
    # plus every autorun.
    last_status: MqttConnectionStatus | None = None

    try:
        while not end_event.is_set():
            # Cleared *before* the config is read, never after: a change that
            # lands from here on re-sets the flag and is picked up on the next
            # pass. Clearing afterwards would drop a change that arrived while
            # the previous session was tearing down.
            bridge.settings_changed.clear()

            target: ConnectionTarget | None = None
            try:
                # The pre-flight reads sit inside the `try` too: they read
                # other services' slices, and an unexpected raise there used to
                # escape the loop and leave the bridge dead until the process
                # restarted.
                target = _resolve_target()
                if (
                    target is None
                    or not get_mqtt_components()
                    or not _is_broker_reachable(target)
                ):
                    if last_status is not MqttConnectionStatus.DISABLED:
                        last_status = MqttConnectionStatus.DISABLED
                        store.dispatch(
                            MqttSetStatusAction(
                                status=MqttConnectionStatus.DISABLED,
                            ),
                        )
                    await _idle(bridge, RECONNECT_MIN)
                    continue

                if not serial:
                    serial = device_serial()

                last_status = MqttConnectionStatus.CONNECTING
                store.dispatch(
                    MqttSetStatusAction(status=MqttConnectionStatus.CONNECTING),
                )
                await _session(serial, target, bridge)
            except aiomqtt.MqttError as exception:
                logger.warning(
                    'MQTT: session ended',
                    extra={'error': str(exception)},
                )
                last_status = MqttConnectionStatus.ERROR
                store.dispatch(
                    MqttSetStatusAction(
                        status=MqttConnectionStatus.ERROR,
                        error=str(exception),
                    ),
                )
                await _idle(bridge, backoff)
                backoff = min(backoff * 2, RECONNECT_MAX)
            # Anything that is not an `MqttError` — a malformed contribution, a
            # bad discovery payload, a missing store slice in the pre-flight —
            # would otherwise escape this loop and leave the bridge dead until
            # the process restarts. `CancelledError` is a `BaseException` in
            # 3.11, so this arm is already cancellation-safe; do not "fix" it
            # by narrowing or re-raising.
            except Exception as exception:
                logger.exception(
                    'MQTT: session crashed',
                    extra={'host': target.host if target is not None else None},
                )
                with contextlib.suppress(Exception):
                    report_service_error()
                last_status = MqttConnectionStatus.ERROR
                store.dispatch(
                    MqttSetStatusAction(
                        status=MqttConnectionStatus.ERROR,
                        error=str(exception),
                    ),
                )
                await _idle(bridge, backoff)
                backoff = min(backoff * 2, RECONNECT_MAX)
            else:
                backoff = RECONNECT_MIN
    finally:
        _announce_event = None
        _settings_changed = None
        _scope = None
        with contextlib.suppress(Exception):
            store.dispatch(
                MqttSetStatusAction(status=MqttConnectionStatus.DISABLED),
            )
