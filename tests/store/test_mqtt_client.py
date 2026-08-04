"""Tests for the impure half of the MQTT bridge.

Covers the two things a refactor of this module can silently break: the order
in which a fresh session announces itself (Home Assistant must never see an
entity it already believes is offline), and the guards on `enqueue`, which is
what stops `MqttPublishAction` — reachable over gRPC — from publishing anywhere
on the broker.

A local fake stands in for `aiomqtt.Client`; no broker is started.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, Self

import pytest

from tests.service_loader import load_service_modules
from ubo_app.store.services.mqtt import (
    BUNDLED_BROKER_PASSWORD_SECRET_ID,
    BUNDLED_BROKER_USERNAME,
    MqttBrokerConfig,
    MqttComponent,
    MqttPublishEvent,
    MqttState,
)
from ubo_app.utils.mqtt_registry import (
    clear_all_mqtt_components,
    register_mqtt_components,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

_M = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '050-mqtt',
    'client',
)
client = _M[0]


class Published(NamedTuple):
    """One recorded `publish` call."""

    topic: str
    payload: Any
    qos: int
    retain: bool


class FakeTopic:
    """A topic that can be compared and wildcard-matched like aiomqtt's."""

    def __init__(self, value: str) -> None:
        """Hold the topic string."""
        self.value = value

    def __str__(self) -> str:
        """Render the topic the way the bridge logs and republishes it."""
        return self.value

    def matches(self, pattern: str) -> bool:
        """Match an MQTT filter, honouring `+` and `#`."""
        parts = self.value.split('/')
        filters = pattern.split('/')
        for index, chunk in enumerate(filters):
            if chunk == '#':
                return True
            if index >= len(parts):
                return False
            if chunk not in ('+', parts[index]):
                return False
        return len(parts) == len(filters)


class FakeMessage(NamedTuple):
    """One inbound message."""

    topic: FakeTopic
    payload: bytes
    retain: bool = False


class FakeMqttClient:
    """Records what a session does, in order."""

    def __init__(self, inbox: list[FakeMessage] | None = None) -> None:
        """Start with an empty log and nothing published."""
        self.published: list[Published] = []
        self.subscribed: list[str] = []
        # Interleaved log of every call, so ordering can be asserted.
        self.calls: list[str] = []
        # Lets a test await the first publish instead of polling.
        self.did_publish = asyncio.Event()
        self.inbox = list(inbox or [])
        self._messages: AsyncIterator[FakeMessage] | None = None

    @property
    def messages(self) -> AsyncIterator[FakeMessage]:
        """Yield the inbox, then block forever — as one shared iterator.

        aiomqtt backs `client.messages` with a single shared queue, so two
        concurrent consumers steal from each other. Handing out the *same*
        iterator every time is what makes a test notice if the bridge ever grows
        a second `async for` over it.
        """
        if self._messages is None:
            self._messages = self._drain()
        return self._messages

    async def _drain(self) -> AsyncIterator[FakeMessage]:
        for message in self.inbox:
            yield message
        await asyncio.Event().wait()

    async def publish(
        self,
        topic: str,
        payload: Any = None,  # noqa: ANN401
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        """Record a publish."""
        self.published.append(Published(topic, payload, qos, retain))
        self.calls.append(f'publish:{topic}')
        self.did_publish.set()

    async def subscribe(self, topic: str, *, qos: int = 0) -> None:
        """Record a subscription."""
        _ = qos
        self.subscribed.append(topic)
        self.calls.append(f'subscribe:{topic}')


class FakeSessionClient(FakeMqttClient):
    """A fake that also satisfies ``async with aiomqtt.Client(...)``."""

    async def __aenter__(self) -> Self:
        """Hand the connected client over, like aiomqtt does."""
        return self

    async def __aexit__(self, *_exception: object) -> None:
        """Nothing to tear down."""


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Consent is read off the store, which has no `mqtt` slice here: the unit
    # tier loads no services. Default to allowed so the commandable-entity
    # filter is not silently exercised in every test; the tests that care about
    # it patch this themselves.
    monkeypatch.setattr(client, '_is_remote_control_allowed', lambda: True)
    # `monkeypatch` rather than direct assignment so the module globals are
    # restored even if a test fails part-way through.
    monkeypatch.setattr(client, '_queue', None)
    monkeypatch.setattr(client, '_settings_changed', None)
    clear_all_mqtt_components()
    yield
    clear_all_mqtt_components()


def _bridge() -> Any:  # noqa: ANN401 - the service module's own dataclass
    return client.BridgeState(
        queue=asyncio.Queue(),
        announce_event=asyncio.Event(),
        end_event=asyncio.Event(),
    )


def _live(payload: dict[str, Any]) -> set[str]:
    """Component ids in a payload, minus the inbound-command bookkeeping.

    Every announce also carries a tombstone for each command entity that is not
    currently offered — the retained discovery message has to be corrected after
    a restart, not merely omitted. Those are asserted in
    `test_mqtt_ha_commands.py`; here they are noise.
    """
    return {
        component_id
        for component_id in payload['cmps']
        if not component_id.startswith('cmd_')
    }


def _component(component_id: str = 'a') -> MqttComponent:
    return MqttComponent(
        component_id=component_id,
        platform='sensor',
        name=component_id,
        state_channel=f'{component_id}/state',
    )


async def test_discovery_is_retained_and_qos_1() -> None:
    """A lost discovery message is silent until the next reconnect."""
    register_mqtt_components('sensors', lambda: [_component()])
    fake = FakeMqttClient()

    await client._publish_discovery(fake, 'abc', {})  # noqa: SLF001

    (message,) = fake.published
    assert message.topic == 'homeassistant/device/ubo_abc/config'
    assert message.retain is True
    assert message.qos == 1
    assert _live(json.loads(message.payload)) == {'a'}


async def test_discovery_retires_components_that_went_away() -> None:
    """An unplugged sensor must disappear, not linger as "unavailable"."""
    register_mqtt_components('sensors', lambda: [_component('b')])
    fake = FakeMqttClient()
    published = {'a': 'sensor', 'b': 'sensor'}

    await client._publish_discovery(fake, 'abc', published)  # noqa: SLF001

    components = json.loads(fake.published[0].payload)['cmps']
    # The platform is required on a removal; a bare `{}` is ignored by
    # Home Assistant and the entity never goes away.
    assert components['a'] == {'p': 'sensor'}
    assert components['b'] != {'p': 'sensor'}
    # The bridge now tracks only what is live, so 'a' is not retired twice.
    assert published == {'b': 'sensor'}


async def test_retirement_survives_a_reconnect() -> None:
    """`published` is owned by the supervisor, not by one session.

    A sensor unplugged while the bridge is disconnected must still be retired on
    the next announce. When this was session-local the set was recreated empty
    on every reconnect, so the retirement was never emitted and the entity stuck
    around in Home Assistant forever.
    """
    published: dict[str, str] = {}
    register_mqtt_components('sensors', lambda: [_component('a')])
    await client._publish_discovery(FakeMqttClient(), 'abc', published)  # noqa: SLF001
    assert published == {'a': 'sensor'}

    # The sensor goes away while the bridge is down, then a new session opens.
    clear_all_mqtt_components()
    register_mqtt_components('sensors', list)
    reconnected = FakeMqttClient()
    await client._publish_discovery(reconnected, 'abc', published)  # noqa: SLF001

    retired = json.loads(reconnected.published[0].payload)['cmps']
    assert retired['a'] == {'p': 'sensor'}
    assert _live(json.loads(reconnected.published[0].payload)) == {'a'}
    assert published == {}


async def test_a_settings_change_cuts_the_retry_wait_short() -> None:
    """Correcting a wrong password must not wait out the backoff.

    The supervisor can be sitting on a 60 s backoff, or a 5 s idle tick while
    disabled. A plain `asyncio.sleep` there means the user changes a setting and
    nothing appears to happen; waking on the flag is what makes the menu feel
    connected to the bridge.
    """
    bridge = _bridge()
    bridge.settings_changed.set()

    async with asyncio.timeout(1):
        await client._idle(bridge, client.RECONNECT_MAX)  # noqa: SLF001


async def test_the_retry_wait_is_honoured_when_nothing_changed() -> None:
    """The early wake must not turn the backoff into a busy loop."""
    bridge = _bridge()
    loop = asyncio.get_running_loop()

    started = loop.time()
    await client._idle(bridge, 0.05)  # noqa: SLF001

    assert loop.time() - started >= 0.05


async def test_a_stop_request_cuts_the_idle_wait_short() -> None:
    """A stop while idling or backing off must not wait out the timer.

    The bridge can be sitting on a 60 s backoff when the service stops, and
    the 5 s cleanup grace would blow long before a settings-only wait woke —
    leaving the supervisor's `finally` unreached and the status stuck.
    """
    bridge = _bridge()
    bridge.end_event.set()

    async with asyncio.timeout(1):
        await client._idle(bridge, client.RECONNECT_MAX)  # noqa: SLF001


async def test_a_clean_stop_still_publishes_a_retained_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stopping the service must leave a retained `offline` behind.

    `TaskScope.aclose` cancels the session's racing tasks, `asyncio.wait` puts
    cancelled tasks in `done` too, and `Task.exception()` *raises* on one —
    before the guard, the `CancelledError` escaped `_session`, skipped the
    graceful `offline` publish, and sailed past `bridge_task`'s
    `except Exception` arm.
    """
    fake = FakeSessionClient()
    monkeypatch.setattr(client.aiomqtt, 'Client', lambda **_kwargs: fake)
    bridge = _bridge()
    target = client.ConnectionTarget(MqttBrokerConfig(), None)

    session = asyncio.create_task(client._session('abc', target, bridge))  # noqa: SLF001
    async with asyncio.timeout(5):
        await fake.did_publish.wait()
    # Let the session reach its `asyncio.wait` before pulling the rug.
    for _ in range(10):
        await asyncio.sleep(0)

    bridge.end_event.set()
    await bridge.scope.aclose()
    async with asyncio.timeout(1):
        # A clean stop: no `CancelledError` may escape here.
        await session

    assert fake.published[-1] == Published(
        'ubo/abc/availability',
        b'offline',
        1,
        True,  # noqa: FBT003
    )


def test_a_missing_docker_slice_reads_as_not_running() -> None:
    """The docker service can be disabled, and then the slice does not exist."""
    assert client._is_home_assistant_up.__wrapped__(None) is False  # noqa: SLF001


async def test_bridge_task_survives_a_failing_pre_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raise while resolving the target must back off, not kill the loop.

    `_is_home_assistant_up` reads another service's slice, which does not
    exist while the docker service is disabled — before the pre-flight moved
    inside the `try`, the `AttributeError` escaped the loop and the bridge was
    dead for the life of the process.
    """

    def _target(*, force: bool = False) -> Any:  # noqa: ANN401
        _ = force
        return client.ConnectionTarget(MqttBrokerConfig(), None)

    def _missing_slice() -> bool:
        raise AttributeError(client.HOME_ASSISTANT_COMPOSITION_ID)

    monkeypatch.setattr(client, '_resolve_target', _target)
    monkeypatch.setattr(client, '_is_home_assistant_up', _missing_slice)
    monkeypatch.setattr(client, '_last_published', dict)
    register_mqtt_components('sensors', lambda: [_component()])

    end_event = asyncio.Event()
    task = asyncio.create_task(client.bridge_task(end_event))
    for _ in range(20):
        await asyncio.sleep(0)
    assert not task.done()

    end_event.set()
    async with asyncio.timeout(1):
        await task


async def test_request_reconnect_reaches_the_live_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The store autorun reaches the bridge through this module-level hook."""
    bridge = _bridge()
    monkeypatch.setattr(client, '_settings_changed', bridge.settings_changed)

    client.request_reconnect()

    assert bridge.settings_changed.is_set()


def test_request_reconnect_is_a_no_op_without_a_supervisor() -> None:
    """The autorun fires before `bridge_task` starts, and after it stops."""
    client.request_reconnect()


async def _drive(client_: FakeMqttClient, bridge: Any = None) -> None:  # noqa: ANN401
    """Run the dispatcher over a fake inbox and stop once it is drained."""
    task = asyncio.create_task(
        client._dispatch_messages(  # noqa: SLF001
            client_,
            'abc',
            bridge if bridge is not None else _bridge(),
        ),
    )
    try:
        for _ in range(20):
            await asyncio.sleep(0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_a_command_is_routed_to_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dispatcher's job is routing; the table decides what a payload means."""
    seen: list[tuple[str, bytes]] = []
    monkeypatch.setattr(
        client.commands,
        'dispatch',
        lambda name, payload: seen.append((name, payload)),
    )

    await _drive(
        FakeMqttClient(
            [FakeMessage(FakeTopic('ubo/abc/command/chime'), b'done')],
        ),
    )

    assert seen == [('chime', b'done')]


async def test_a_retained_command_is_dropped_and_its_slot_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained command re-fires on every reconnect, forever.

    Dropping it is not enough — the retained message stays on the broker and
    replays again next time, so the slot is cleared with an empty retained
    publish.
    """
    seen: list[str] = []
    monkeypatch.setattr(
        client.commands,
        'dispatch',
        lambda name, _payload: seen.append(name),
    )
    fake = FakeMqttClient(
        [FakeMessage(FakeTopic('ubo/abc/command/chime'), b'done', retain=True)],
    )

    await _drive(fake)

    assert seen == []
    assert fake.published == [Published('ubo/abc/command/chime', b'', 0, True)]  # noqa: FBT003


async def test_a_failing_handler_does_not_end_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression test for the bridge dying on one bad message.

    Before the handler was wrapped, an exception here propagated out of the
    session and past `bridge_task`'s `MqttError`-only arm, leaving the bridge
    dead until the process restarted.
    """
    seen: list[str] = []

    def _explode_once(name: str, _payload: bytes) -> None:
        seen.append(name)
        if len(seen) == 1:
            msg = 'boom'
            raise RuntimeError(msg)

    monkeypatch.setattr(client.commands, 'dispatch', _explode_once)

    await _drive(
        FakeMqttClient(
            [
                FakeMessage(FakeTopic('ubo/abc/command/chime'), b'done'),
                FakeMessage(FakeTopic('ubo/abc/command/ring.off'), b'PRESS'),
            ],
        ),
    )

    assert seen == ['chime', 'ring.off']


async def test_the_birth_message_republishes_availability() -> None:
    """Home Assistant expects integrations to re-announce when it comes back."""
    fake = FakeMqttClient(
        [FakeMessage(FakeTopic('homeassistant/status'), b'online')],
    )

    await _drive(fake)

    assert fake.published == [Published('ubo/abc/availability', 'online', 1, True)]  # noqa: FBT003


async def test_a_birth_flood_is_debounced() -> None:
    """Two births in quick succession must cost one announce, not two.

    `homeassistant/status` is broker-wide — any peer can publish `online` to it
    repeatedly, and each handled birth is a full discovery rebuild plus a
    retained republish.
    """
    fake = FakeMqttClient(
        [
            FakeMessage(FakeTopic('homeassistant/status'), b'online'),
            FakeMessage(FakeTopic('homeassistant/status'), b'online'),
        ],
    )

    await _drive(fake)

    assert fake.published == [Published('ubo/abc/availability', 'online', 1, True)]  # noqa: FBT003


async def test_an_offline_birth_message_is_ignored() -> None:
    """Only `online` means Home Assistant is asking to be told again."""
    fake = FakeMqttClient(
        [FakeMessage(FakeTopic('homeassistant/status'), b'offline')],
    )

    await _drive(fake)

    assert fake.published == []


async def test_an_unrouted_topic_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another pod's traffic on a shared LAN broker is not ours to act on."""
    seen: list[str] = []
    monkeypatch.setattr(
        client.commands,
        'dispatch',
        lambda name, _payload: seen.append(name),
    )
    fake = FakeMqttClient(
        [FakeMessage(FakeTopic('ubo/other/command/chime'), b'done')],
    )

    await _drive(fake)

    assert seen == []
    assert fake.published == []


async def test_commandable_entities_are_withheld_while_control_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A button nothing is subscribed to looks working and silently is not.

    Filtered centrally so it covers every contributor — including the infrared
    buttons, which are declared unconditionally by their own service.
    """
    monkeypatch.setattr(client, '_is_remote_control_allowed', lambda: False)
    register_mqtt_components(
        'x',
        lambda: [
            _component('reading'),
            MqttComponent(
                component_id='press',
                platform='button',
                name='Press',
                command_channel='command/press',
            ),
        ],
    )
    fake = FakeMqttClient()

    await client._publish_discovery(fake, 'abc', {})  # noqa: SLF001

    assert set(json.loads(fake.published[0].payload)['cmps']) == {'reading'}


async def test_a_withdrawn_commandable_entity_is_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning control off must remove the buttons, not just stop serving them.

    Discovery is retained, so an entity that merely stops being mentioned stays
    on the dashboard.
    """
    monkeypatch.setattr(client, '_is_remote_control_allowed', lambda: False)
    register_mqtt_components('x', list)
    fake = FakeMqttClient()

    await client._publish_discovery(fake, 'abc', {'press': 'button'})  # noqa: SLF001

    assert json.loads(fake.published[0].payload)['cmps'] == {'press': {'p': 'button'}}


@pytest.mark.parametrize(
    ('event', 'why'),
    [
        pytest.param(
            MqttPublishEvent(channel='a/state', payload='1', qos=3),
            'paho raises on an out-of-range QoS',
            id='bad-qos',
        ),
        pytest.param(
            MqttPublishEvent(channel='a' * 600, payload='1'),
            'paho raises on an oversized topic',
            id='oversized-channel',
        ),
        pytest.param(
            MqttPublishEvent(channel='a\x00b', payload='1'),
            'a null byte is not valid in a topic',
            id='null-byte',
        ),
        pytest.param(
            MqttPublishEvent(channel='a/state', payload='x' * 70000),
            'an unbounded payload is a memory vector',
            id='oversized-payload',
        ),
    ],
)
def test_enqueue_refuses_a_publish_paho_would_reject(
    event: MqttPublishEvent,
    why: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`MqttPublishEvent` is reachable over gRPC, so every field is untrusted.

    The pump hands these straight to paho, and an exception there ends the
    session and starts the reconnect backoff — so one malformed event from any
    client would knock the bridge offline.
    """
    _ = why
    queue: asyncio.Queue[MqttPublishEvent] = asyncio.Queue()
    monkeypatch.setattr(client, '_queue', queue)

    client.enqueue(event)

    assert queue.empty()


@pytest.mark.parametrize('qos', [0, 1, 2])
def test_enqueue_accepts_every_valid_qos(
    qos: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must not narrow what MQTT itself allows."""
    queue: asyncio.Queue[MqttPublishEvent] = asyncio.Queue()
    monkeypatch.setattr(client, '_queue', queue)

    client.enqueue(MqttPublishEvent(channel='a/state', payload='1', qos=qos))

    assert queue.qsize() == 1


def test_publishes_are_dropped_while_disconnected() -> None:
    """Buffering across a disconnect looks helpful and is not.

    The queue would fill with the *oldest* events, discard every newer one, and
    then replay the stale ones on reconnect — an infrared event from an hour ago
    firing a Home Assistant automation.
    """
    client.enqueue(MqttPublishEvent(channel='a/state', payload='1'))

    # Nothing was accepted, so there is nothing to replay.
    assert client._queue is None  # noqa: SLF001


async def test_publishes_are_accepted_only_for_the_life_of_a_session() -> None:
    """The window opens on connect and closes again on disconnect."""
    queue: asyncio.Queue[MqttPublishEvent] = asyncio.Queue()

    with client._accept_publishes(queue):  # noqa: SLF001
        client.enqueue(MqttPublishEvent(channel='a/state', payload='1'))
        assert queue.qsize() == 1

    assert client._queue is None  # noqa: SLF001
    # And whatever the pump had not sent yet is discarded rather than held over.
    assert queue.qsize() == 0
    client.enqueue(MqttPublishEvent(channel='a/state', payload='2'))
    assert queue.qsize() == 0


async def test_the_pump_prefixes_the_pod_namespace() -> None:
    """Producers hand over a relative channel; the bridge owns the prefix."""
    fake = FakeMqttClient()
    queue: asyncio.Queue[MqttPublishEvent] = asyncio.Queue()
    await queue.put(
        MqttPublishEvent(
            channel='bme280_0x76/state',
            payload='{"temperature": 21.4}',
            retain=True,
            qos=1,
        ),
    )

    task = asyncio.create_task(client._pump(fake, 'abc', queue))  # noqa: SLF001
    try:
        async with asyncio.timeout(5):
            await fake.did_publish.wait()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    (message,) = fake.published
    assert message.topic == 'ubo/abc/bme280_0x76/state'
    assert message.payload == '{"temperature": 21.4}'
    assert message.retain is True
    assert message.qos == 1


def test_enqueue_without_a_session_is_a_no_op() -> None:
    """Readings arrive before the broker is up; they are dropped, not queued."""
    client.enqueue(MqttPublishEvent(channel='a/state', payload='1'))


@pytest.mark.parametrize(
    'channel',
    ['/absolute', 'wild/#', 'wild/+/card', '../escape', ''],
)
def test_enqueue_refuses_to_escape_the_pod_namespace(
    channel: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`MqttPublishAction` is reachable over gRPC — this is the guard."""
    queue: asyncio.Queue[MqttPublishEvent] = asyncio.Queue()
    monkeypatch.setattr(client, '_queue', queue)

    client.enqueue(MqttPublishEvent(channel=channel, payload='1'))

    assert queue.empty()


def test_enqueue_refuses_the_pod_own_command_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A publish must not echo back through the pod's own command topics.

    The session subscribes to `ubo/<serial>/command/#`, so a publish landing
    there would come straight back through `_route` and into the command table.
    """
    queue: asyncio.Queue[MqttPublishEvent] = asyncio.Queue()
    monkeypatch.setattr(client, '_queue', queue)

    client.enqueue(MqttPublishEvent(channel='command/chime', payload='done'))

    assert queue.empty()


def test_enqueue_accepts_a_relative_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordinary case still reaches the session."""
    queue: asyncio.Queue[MqttPublishEvent] = asyncio.Queue()
    monkeypatch.setattr(client, '_queue', queue)

    client.enqueue(MqttPublishEvent(channel='a/state', payload='1'))

    assert queue.qsize() == 1


def test_enqueue_drops_on_overflow_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telemetry supersedes itself; a full queue must not break the producer."""
    queue: asyncio.Queue[MqttPublishEvent] = asyncio.Queue(maxsize=1)
    monkeypatch.setattr(client, '_queue', queue)

    client.enqueue(MqttPublishEvent(channel='a/state', payload='1'))
    client.enqueue(MqttPublishEvent(channel='a/state', payload='2'))

    assert queue.qsize() == 1


def test_the_bundled_broker_presents_the_generated_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bundled broker's host-loopback listener is authenticated.

    The docker service generates the credential when it renders the
    composition; the bridge reads it from the secrets file. A *missing* secret
    means the composition has not been prepared yet — it must not be cached,
    so its later appearance is picked up without a settings change.
    """
    secrets: dict[str, str] = {}
    monkeypatch.setattr(client, 'read_secret', secrets.get)
    monkeypatch.setattr(client, '_password_cache', {})
    state = MqttState(is_enabled=True, broker=MqttBrokerConfig())

    target = client._resolve_target.__wrapped__(state)  # noqa: SLF001
    assert target is not None
    assert target.username == BUNDLED_BROKER_USERNAME
    assert target.password is None

    secrets[BUNDLED_BROKER_PASSWORD_SECRET_ID] = 'generated'
    target = client._resolve_target.__wrapped__(state)  # noqa: SLF001
    assert target is not None
    assert target.password == 'generated'  # noqa: S105
