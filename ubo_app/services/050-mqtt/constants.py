"""Constants for the MQTT bridge service."""

from __future__ import annotations

# The composition that ships the bundled broker; read off the docker slice
# rather than imported, as services are not importable across each other.
HOME_ASSISTANT_COMPOSITION_ID = 'home_assistant'

LOOPBACK_HOSTS = frozenset({'127.0.0.1', 'localhost', '::1'})

DISCOVERY_PREFIX = 'homeassistant'
HA_STATUS_TOPIC = f'{DISCOVERY_PREFIX}/status'

# `MqttPublishEvent` is reachable over gRPC, so an outbound publish is as
# untrusted as an inbound command. Paho raises on an oversized topic, and an
# exception in the pump ends the session.
MAX_TOPIC_BYTES = 512
MAX_OUTBOUND_PAYLOAD = 65536

# An inbound payload is a notification body or a number at most; anything
# larger is a mistake or an attempt to flood the screen.
MAX_COMMAND_PAYLOAD = 4096
MAX_NOTIFICATION_MESSAGE = 256
MAX_NOTIFICATION_TITLE = 64
MAX_NOTIFICATION_ICON = 16

# An utterance bound, well under `MAX_COMMAND_PAYLOAD`. Roughly half a minute of
# speech; the payload cap alone would let a caller occupy the speaker for
# minutes, and unlike a notification there is no way to dismiss one early.
MAX_SPEAK_TEXT = 512

# Rate limits for inbound commands. One-shot side effects are capped outright;
# ring updates are throttled instead, because the newest value is the one the
# user means.
NOTIFY_RATE_BURST = 5
NOTIFY_RATE_WINDOW = 10
RING_COALESCE_INTERVAL = 0.1
# Each send shells out to `ir-ctl` behind a lock, fed by an unbounded queue in
# `090-infrared`, so this is what stops a button flooding it.
IR_SEND_MIN_INTERVAL = 0.5
# Speech is a one-shot side effect like a chime, but a far longer one. The
# assistant subprocess caps synthesis concurrency at 3, so an unthrottled topic
# produces *overlapping voices* rather than a queue.
SPEAK_MIN_INTERVAL = 2.0

# How long "Test Connection" waits before calling a broker unreachable.
PROBE_TIMEOUT = 10

# `homeassistant/status` is broker-wide, so any peer can publish `online` to it
# repeatedly — and every birth costs a full discovery rebuild and a retained
# republish. Repeats inside this window are ignored.
BIRTH_DEBOUNCE_INTERVAL = 5

RECONNECT_MIN = 5
RECONNECT_MAX = 60

# Several producers share the outbound queue now, so it is deeper than the
# single-producer version it replaces. Overflow is still dropped — these are
# live telemetry ticks that the next one supersedes — but it is logged.
OUTBOUND_QUEUE_SIZE = 64
OUTBOUND_OVERFLOW_LOG_INTERVAL = 10

MQTT_SETTINGS_MENU_ID = 'mqtt:settings'
MQTT_BROKER_MENU_ID = 'mqtt:broker'

MQTT_PASSWORD_SECRET_ID = 'MQTT_PASSWORD'  # noqa: S105 — a secret's id, not its value
