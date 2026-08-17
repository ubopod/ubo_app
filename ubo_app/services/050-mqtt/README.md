# MQTT Bridge Service (`050-mqtt`)

## Overview

The pod's single connection to an MQTT broker, and the bridge between it and the Redux bus. Any
service can surface state and events to Home Assistant, Frigate, Node-RED, or any other client on
the broker without owning a client of its own — services cannot import each other, so they reach the
bridge through the store.

It loads in the `050-` integration tier, alongside `ssh`, `tailscale` and `rpi-connect`. Load order
does not matter: `_wait_for_reducers()` (`ubo_app/service_thread.py:214`) guarantees every slice
exists before any service's `init_service()` runs, and a contributor that registers after the bridge
has already announced simply dispatches `MqttRequestAnnounceAction`.

For the action/event/store model, see
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## Files

| Path            | Purpose                                                                          |
| --------------- | -------------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration (`service_id='mqtt'`); registers the reducer, returns `init_service()`'s subscriptions. |
| `setup.py`      | Starts the session supervisor, registers persistence, subscribes the bridge events. |
| `reducer.py`    | Pure reducer for the `mqtt` slice.                                                |
| `menu.py`       | The Settings → Network → MQTT page, the broker picker and the broker form.         |
| `commands.py`   | What Home Assistant may make the pod do, and how each payload is parsed.           |
| `ha_commands.py`| **Pure.** Those commands rendered as Home Assistant entities.                      |
| `constants.py`  | Topic prefixes, backoff bounds, queue size, rate limits, secret ids.               |
| `topics.py`     | Topic layout and the relative-channel guard. Pure except `device_serial` (reads the serial/pod id). |
| `discovery.py`  | The Home Assistant device-level discovery payload. Pure except `get_pod_id` (reads the pod-id file). |
| `client.py`     | **Impure.** The only module that imports `aiomqtt`: session, supervisor, backoff, LWT. |
| `task_scope.py` | A group of session tasks, cancelled together. Local: nothing else needs it.        |

Store types: [`ubo_app/store/services/mqtt.py`](../../store/services/mqtt.py) — serializable types
only, because the proto generator turns everything in that package into a gRPC message.

The contribution registry is separate, in
[`ubo_app/utils/mqtt_registry.py`](../../utils/mqtt_registry.py): it is a dict of provider callables
executed by the bridge, which could never cross a wire. It sits outside any service because services
cannot import each other, and outside `store/core`, which has no business knowing about MQTT.

The pure/impure split is load-bearing: `topics.py` and `discovery.py` never import `aiomqtt` and do
no broker I/O (their only reads are the device serial and the pod id), so the wire contract with
Home Assistant is pinned by unit tests against golden payloads rather than by starting a broker.

## State

Slice: `state.mqtt` — [`MqttState`](../../store/services/mqtt.py):

| Field                  | Type                     | Meaning                                                    |
| ---------------------- | ------------------------ | ---------------------------------------------------------- |
| `status`               | `MqttConnectionStatus`   | disabled / connecting / connected / error.                 |
| `broker`               | `MqttBrokerConfig`       | Target broker (persisted). The password lives in `.secrets.env`, never here. |
| `is_enabled`           | `bool`                   | Master switch (persisted).                                 |
| `allow_remote_control` | `bool`                   | Inbound commands, off by default (persisted).              |
| `last_error`           | `str \| None`            | Cleared as soon as the status leaves `error`.              |
| `published_components` | `dict[str, str]`         | Component id → platform, as last announced (persisted). Discovery is retained, so this is what lets an entity removed while the pod was off still be retired. |

> Deliberately **not** in state: message counters, byte totals, last-message timestamps. The
> all-services integration snapshot is a full-state golden, so a monotonic field would make it
> flaky. Diagnostics go to `logger`.

## Actions & Events

| Action                             | Result                                                                 |
| ---------------------------------- | ---------------------------------------------------------------------- |
| `MqttPublishAction`                | **Transparent** — state unchanged, emits `MqttPublishEvent`.           |
| `MqttRequestAnnounceAction`        | **Transparent** — state unchanged, emits `MqttAnnounceRequestedEvent`. |
| `MqttSetStatusAction`              | Writes `status`; `last_error` only survives while erroring.            |
| `MqttSetBrokerAction`              | Writes `broker`.                                                       |
| `MqttSetEnabledAction`             | Writes `is_enabled`.                                                   |
| `MqttSetAllowRemoteControlAction`  | Writes `allow_remote_control`.                                         |
| `MqttSetPublishedComponentsAction` | Writes `published_components` after every announce.                    |

The two transparent arms are the whole reason cross-service publishing works. They must leave state
identical — a 1 Hz sensor reading passing through the store must not churn it.

## Contributing to the bridge

Two independent things, from any service:

**1. Declare entities.** Register a *provider* — a callable, not a list, because the set is live:

```python
from ubo_app.utils.mqtt_registry import register_mqtt_components

unregister = register_mqtt_components('sensors', _my_components)
# ... and return `unregister` in init_service()'s subscriptions.
```

`MqttComponent` is spelled in **Home Assistant's** vocabulary, not your service's, so the bridge
never learns your state shape. Component ids are *not* namespaced by `source_id` — keep your own
unique. When your set changes, dispatch `MqttRequestAnnounceAction()`.

**2. Publish data.** Dispatch with a **relative** channel; the bridge owns `ubo/<serial>/`:

```python
store.dispatch(MqttPublishAction(channel=f'{device_id}/state', payload=json.dumps(readings)))
```

Absolute paths, wildcards and traversals are rejected (`topics.is_relative`) rather than rewritten —
`MqttPublishAction` is auto-enrolled into the gRPC surface, so this is the guard that keeps a remote
client from publishing anywhere on the broker.

## Topics

| Purpose      | Topic                                     | QoS | Retain |
| ------------ | ----------------------------------------- | --- | ------ |
| Discovery    | `homeassistant/device/ubo_{serial}/config` | 1   | yes    |
| Availability | `ubo/{serial}/availability`                | 1   | yes    |
| Last will    | same, payload `offline`                    | 1   | yes    |
| Producer data| `ubo/{serial}/{channel}`                   | per-publish | per-publish |
| Subscribed   | `homeassistant/status`                     | 1   | —      |
| Subscribed   | `ubo/{serial}/command/#` — only while Home Assistant control is on | 0 | — |

`{serial}` is the HAT EEPROM serial, falling back to the pod id.

## Runtime

`bridge_task` is a supervisor loop. It idles (status `disabled`, 5 s tick) until the bridge is
enabled, at least one service has contributed an entity, **and** the broker looks reachable — for
the bundled broker that means the Home Assistant composition is up, read straight off
`state.docker` rather than by importing the docker service.

A session then: connects → dispatches `connected` → publishes availability `online` → subscribes to
`homeassistant/status` → publishes discovery. Availability goes first so Home Assistant never sees an
entity it already believes is offline. Five tasks then race (`FIRST_COMPLETED`): the publish pump,
`_dispatch_messages` — the single inbound router; a second `async for` over `client.messages` would
steal messages — the announce-request watcher, the service's end event, and the settings-changed
event. A Home Assistant birth (`homeassistant/status` = `online`) is handled by that router and
triggers a re-announce, debounced to one per 5 s: the status topic is broker-wide, so any peer can
publish to it. `MqttError` backs off 5 s → doubling → 60 s, reset on a clean session end.
Anything that is *not* an `MqttError` is caught too — before that arm existed, one bad discovery
payload left the bridge dead until the process restarted.

`BridgeState` holds what outlives a session: the announce and settings-changed events, and
`published` (component id → platform, as last announced). `published` survives both a reconnect *and*
a restart — it is seeded from the persistent store — because discovery is retained and an entity that
merely stops being mentioned stays on the Home Assistant dashboard.

The outbound queue is deliberately **not** a cross-reconnect buffer: `_accept_publishes` opens it
only while a session is live and drains it on the way out. Buffering looks helpful and is not — the
queue fills with the *oldest* events, discards every newer one, and then replays the stale ones on
reconnect, which for an infrared event means firing an automation from an hour ago.

A session that ends deliberately — bridge switched off, broker changed, service stopping — publishes
a retained `offline` first. The Last Will only covers an ungraceful drop, so without it the broker
keeps reporting a pod that is no longer there as online.

Saving a broker or flipping a switch sets `settings_changed`, which ends the session cleanly and
re-reads the config immediately. The idle and backoff waits watch the same flag *and* the service's
end event, so enabling the bridge or fixing a password takes effect at once instead of after up to a
minute — and a stopping service does not sit out a backoff either.

## Configuration

- Persistent store: `mqtt:broker`, `mqtt:is_enabled`, `mqtt:allow_remote_control`,
  `mqtt:published_components`, `mqtt:bundled_expose_to_lan`, `mqtt:bundled_credentials_revision`.
- Secrets (`~/.config/ubo/.secrets.env`): `MQTT_PASSWORD` (external broker),
  `MQTT_BUNDLED_BROKER_PASSWORD` (generated by the docker service on first render of the bundled
  broker, replaceable from Broker Settings). The revision counter above exists because a
  secrets-only write is invisible to the store: bumping it is what tells the docker service to
  re-render the broker's `password_file` and recreate the container.
- Two broker modes, both reached **outbound** — the pod is never a LAN-facing server:
  - `BUNDLED` — the Mosquitto container in the on-device Home Assistant composition
    (`080-docker/apps/home_assistant.py`), on `127.0.0.1:1883`. **One listener, authenticated for
    everyone** — there is no anonymous path. The same credentials serve `ubo_net` (how HA and peer
    add-ons reach it as `mosquitto:1883`), the host's loopback publish (`ubo-app` runs on the host,
    not in a container, so that is its path — see `_resolve_target`), and, when the user opts in
    via `mqtt:bundled_expose_to_lan`, any client on the network. Auth being the only boundary is
    what lets `mosquitto:1883` stay correct in both of HA's network modes.
    The publish uses compose's *long* syntax so `apply_compose_port_binding` cannot move the broker
    to `0.0.0.0` as a side effect of HA's own expose-to-LAN toggle — the broker's exposure is set
    only from Settings → Network → MQTT → Broker Settings.
  - `EXTERNAL` — Home Assistant on another machine on the LAN, with its own broker. Host, port,
    username, password and TLS come from Settings → Network → MQTT → Broker Settings.
- `_parse_broker` forces the loopback defaults whenever the source is `BUNDLED`, so switching back
  cannot leave a stale external host behind. It also degrades to defaults on a malformed document:
  it runs at *class-definition* time, where an exception is an import-time crash, not a bad setting.

## Testing & Development Notes

| Test                                    | Tier        | What it covers                                        |
| --------------------------------------- | ----------- | ----------------------------------------------------- |
| `tests/store/test_mqtt_discovery.py`     | Unit        | The discovery payload (golden), entity removal.        |
| `tests/store/test_mqtt_topics.py`        | Unit        | Topic layout; the relative-channel guard.              |
| `tests/store/test_mqtt_reducer.py`       | Unit        | Every arm; the two transparent arms leave state alone. |
| `tests/store/test_mqtt_contributions.py` | Unit        | Registration hygiene; a failing provider is isolated.  |
| `tests/store/test_mqtt_client.py`        | Unit        | Discovery retain/QoS, retirement across a reconnect, pump prefixing, `enqueue` guards, the interruptible backoff. |
| `tests/store/test_mqtt_broker_config.py` | Unit        | `serialize_broker`/`_parse_broker` round-trip; corrupt-document fallbacks; `BUNDLED` forcing loopback. |
| `tests/store/test_mqtt_menu.py`          | Unit        | `resolve_password`'s four branches; the two-level path matcher. |
| `tests/store/test_mqtt_commands.py`      | Unit        | Every command against the payload HA really sends; each guard and rate limit. |
| `tests/store/test_mqtt_ha_commands.py`   | Unit        | The command entities' discovery shape; tombstones. |
| `tests/store/test_task_scope.py`         | Unit        | `TaskScope`: cancellation on close, error reporting, refusing tasks after close. |
| `tests/integration/test_services.py`     | Integration | The service registers and the store snapshot matches.  |

**Maintenance when you change this service:**

- **State shape** → regenerate store snapshots (never hand-edit) **and** run `uv run poe proto`
  (`ubo_app/rpc/_class_registry.py` is generated *and* committed). The rpi snapshot needs
  `poe device:test` on real hardware.
- **The discovery key table** (`discovery._SCALAR_KEYS` and friends) → extend
  `test_mqtt_discovery.py`. A wrong Home Assistant key fails *silently*: the entity simply never
  appears. Removal is the same trap in reverse: Home Assistant requires the `p` (platform) key on a
  removal payload, and a bare `{}` is ignored, so the entity never goes away.
- **Test shims** — these tests import service modules by bare name. Anything left in `sys.modules`
  shadows the same filename in another service (`040-sensors` also has a `menu.py`), so the loader
  must purge what it imported and keep only a direct reference.
- **Off-device** there are no sensors and Home Assistant is not running, so the bridge idles in
  `disabled` and never connects. Verify the wire on-device with
  `mosquitto_sub -h 127.0.0.1 -t 'homeassistant/#' -t 'ubo/#' -v`, or against a LAN broker with
  `-h <ha-host> -u <user> -P <pass>`.

## Inbound commands

**Off by default.** The bundled broker authenticates every connection, but a credential shared with
Home Assistant and any other client the user hands it to is not a per-client identity — and a LAN
broker is only as trustworthy as its own auth. `Home Assistant Control` is a user control, not an
authentication boundary — and MQTT discovery has no pairing mechanism that could make it one.

While it is on, the session subscribes to `ubo/<serial>/command/#` and `commands.py` decides what a
payload means. A small hand-written table, deliberately *not* a generic "dispatch any action" topic,
and deliberately not shared with any future MCP surface, so one transport's consent policy does not
silently become another's.

| Command | Entity | Payload Home Assistant sends |
| --- | --- | --- |
| `notify` | `notify` | the raw message text |
| `notify.rich` | none — automation-driven | `{"message": …, "title": …, "chime": …, "display_type": …, "blink": …, "color": …, "icon": …}` |
| `speak` | a second `notify` | the raw message text, read aloud |
| `chime` | `select` | the bare option, e.g. `done` |
| `ring.brightness` | `number` (min 0, max 1, step 0.05) | a bare number, e.g. `0.55` |
| `ring.off` | `button` | `payload_press` |
| `ring.color` | none — automation-driven | `{"r": …, "g": …, "b": …}` |
| `ir.send` | one `button` per registered device (from `090-infrared`) | `protocol:scancode` |

**Home Assistant does not send JSON for most platforms**, which is why every command carries its own
parser instead of sharing one decoder. `notify.send_message` carries a message and nothing else, so
everything a pod notification can also do — chime, ring blink and colour, flash vs. sticky — needs the
JSON `notify.rich` topic, published from an automation. Both share one rate-limit budget: they have
the same user-visible effect. Colour gets no entity because three channels need a `light`,
whose `schema: json` payload is HA's own `state`/`brightness`/`color` shape rather than raw RGB — and
a real light must report state back, which `RgbRingState` cannot: it holds only `is_busy`.

`speak` reads its text aloud instead of showing it. It gets a **second `notify` entity** rather than a
`text` one: `text` is stateful, and with no state topic to report back on it renders as `unknown`. The
text goes to `SpeechSynthesisReadTextAction` — the same front door the screen reader and
`010-localization` use — so the engine and voice are whichever the user selected, and "Prefer Local"
is honoured. Nothing here pins an engine. Note that `ReadableInformation` substitutes `{{hostname}}`
into the text, so an automation can have the pod say its own address.

Guards, each defending something specific:

- **Never a caller-supplied `Notification`.** It is built from scalars, because
  `Notification.actions` can carry a `NotificationDispatchItem(store_action=…)` — an arbitrary action
  fired when the user presses a button. `notify.rich` therefore reads each field explicitly and
  *rejects* an unknown one rather than passing it through.
- **Brightness is range-checked before dispatch.** `as_command()` *raises* outside 0..1, and that
  would run inside the reducer chain.
- **Only numeric colour channels.** `as_command()` interpolates them into a string the rgb-ring
  service splits on whitespace, so a string channel could inject extra tokens.
- **Retained commands are dropped and their slot cleared.** One would otherwise re-fire on every
  reconnect, forever.
- **QoS 0, and `ret: false` on every command entity.** These are one-shot side effects; QoS 1
  redelivery would mean an occasional duplicate chime.
- **Infrared is an allowlist, not a transmitter.** `ir.send` takes the *identifier* of an
  already-registered device, which the pod resolves against `state.infrared.registered_devices`. A
  remote caller cannot ask the pod to emit an arbitrary code.
- **Bounded and rate-limited.** 4 KiB per payload, one chime a second, five notifications per ten
  seconds, one infrared send every half second — `090-infrared`'s send queue is unbounded and each
  send shells out to `ir-ctl` behind a lock. Speech gets its own budget: 512 characters and one
  utterance every two seconds, because the assistant synthesizes up to three at once, so
  back-to-back requests would *overlap audibly* rather than queue — and unlike a notification, a
  spoken line occupies the speaker until it finishes and cannot be dismissed early. Ring updates are
  *coalesced* rather than throttled — a slider drag must end on the value the user released at,
  which plain throttling would drop.

Turning control off retires the entities. The bridge filters **every** component carrying a
`command_channel` out of the announce while control is off — once, centrally, so a contributor cannot
forget to check consent and so the infrared buttons are covered without knowing about it. The
`published` diff then emits an explicit `{"p": platform}` removal, which is required: a bare omission
leaves the entity on the dashboard, because discovery is retained.

Registering or unregistering a contributor also requests an announce, so stopping a service takes its
entities with it.

### Sending a notification or speech from Home Assistant

Turn on **Settings → Network → MQTT → Home Assistant Control** on the pod first. Until then the
session does not subscribe to `command/#` at all, the commandable entities are withheld from
discovery, and `dispatch` refuses everything with `remote control is off` — a Home Assistant action
that looks perfectly correct will simply do nothing.

The pod appears as one device named after its pod id (`ubo-7k`, `ubo-a3`, … — two random characters
seeded from the HAT serial). Home Assistant slugifies *device name + entity name* into the entity id,
so the two `notify` entities below land at `notify.ubo_7k_notification` and `notify.ubo_7k_speak`.
**Substitute your own pod's id** — check Developer Tools → States, or the device page, rather than
copying `7k`.

Both entities are `notify`, so both are driven with `notify.send_message`. Where they differ is what
the pod does with the text: one puts it on the screen, the other says it out loud.

#### Show a notification

```yaml
action: notify.send_message
target:
  entity_id: notify.ubo_7k_notification
data:
  message: The kettle boiled
```

The `notify` platform publishes the **raw message text** — no title, no JSON. That is a platform
limitation, not a simplification on the pod's side: no `command_template` is declared because the
discovery docs do not specify which variables such a template would receive, and a wrong guess yields
an entity that silently never works. The pod always titles these "Home Assistant" and flashes them.

#### Speak it instead

```yaml
action: notify.send_message
target:
  entity_id: notify.ubo_7k_speak
data:
  message: The garage door has been open for ten minutes
```

Read aloud with whichever TTS engine the pod is set to use — the same one the screen reader uses, and
"Prefer Local" is honoured. Nothing in the payload selects an engine, deliberately.

The pod substitutes `{{hostname}}` in the text with its own address, but **Home Assistant renders
`message` as a Jinja template first**, so writing it plainly makes HA resolve it as an undefined
variable and the pod never sees it. Escape it to get the literal through:

```yaml
data:
  message: "I am {{ '{{hostname}}' }}"
```

Note this speaks **without** showing anything. To both show and say a line, fire both actions:

```yaml
- action: notify.send_message
  target:
    entity_id: notify.ubo_7k_notification
  data:
    message: Front door unlocked
- action: notify.send_message
  target:
    entity_id: notify.ubo_7k_speak
  data:
    message: Front door unlocked
```

They have separate rate-limit budgets, so neither starves the other.

#### A notification with a title, chime and colour

`notify.send_message` carries a message and nothing else, so anything richer needs `mqtt.publish`
against the `notify.rich` topic, which has no entity by design. This one addresses the pod by
**serial**, not by entity: the serial is the HAT EEPROM value and falls back to the pod id only when
there is no EEPROM, so do not assume it matches the entity ids above. Find it with the
`mosquitto_sub` command at the end of this section — it is the middle segment of the
`ubo/<serial>/availability` topic.

```yaml
action: mqtt.publish
data:
  topic: ubo/<serial>/command/notify.rich
  payload: >-
    {"title": "Laundry", "message": "The washing machine finished",
     "chime": "done", "display_type": "sticky", "color": "#00aaff"}
```

Allowed fields are exactly `title`, `message`, `chime`, `display_type`, `blink`, `color` and `icon`;
an unknown one is **refused, not ignored**, so a typo fails loudly instead of half-working.

#### When nothing happens

Refusals are logged on the pod with the reason, and never raise. The usual causes, in the order worth
checking: Home Assistant Control is off; the payload is empty (`an empty notification` /
`nothing to say`); two requests arrived too close together (`rate limited` — one chime a second, five
notifications per ten seconds, one utterance every two seconds); or the message was `retain: true`,
which is dropped outright and the retained slot cleared, because a retained command re-fires on every
reconnect forever.

To watch the traffic directly:

```bash
mosquitto_sub -h 127.0.0.1 -u ubo -P <password> -t 'ubo/#' -t 'homeassistant/#' -v
```

### Contributed by other services

The bridge owns the transport, not the entities. Any service registers its own via
`register_mqtt_components` and publishes through `MqttPublishAction`:

| Service | Entities |
| --- | --- |
| `040-sensors` | one `sensor` per reading of every detected device |
| `090-infrared` | an `event` for received codes, and one `button` per registered device |

`090-infrared/ha.py` is worth reading alongside this: it is the only contributor that is
*commandable*, so it is the worked example of a service declaring a button whose `payload_press` the
bridge resolves back through `commands.py`.
