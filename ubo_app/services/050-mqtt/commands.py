"""What Home Assistant is allowed to make the pod do, and how it says it.

A small hand-written table, deliberately local to this service. It is *not* a
generic "dispatch any action" bridge and it is *not* shared with any future MCP
surface — one transport's consent policy should not silently become another's.

**Payload shapes are Home Assistant's, not ours.** HA does not send JSON for most
entity platforms: a `select` publishes the bare option string, a `number`
publishes a bare number, a `button` publishes its `payload_press`, and the
`notify` platform publishes the raw message text. So each command carries its
own parser rather than everything sharing one JSON decoder.

Nothing here runs unless `state.mqtt.allow_remote_control` is on. That switch is
a user control, not an authentication boundary: the bundled broker is anonymous
and reachable by every container on `ubo_net`, and a LAN broker is only as
trustworthy as its own auth.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from dataclasses import replace
from typing import TYPE_CHECKING, NamedTuple

from constants import (
    IR_SEND_MIN_INTERVAL,
    MAX_COMMAND_PAYLOAD,
    MAX_NOTIFICATION_ICON,
    MAX_NOTIFICATION_MESSAGE,
    MAX_NOTIFICATION_TITLE,
    NOTIFY_RATE_BURST,
    NOTIFY_RATE_WINDOW,
    RING_COALESCE_INTERVAL,
)
from task_scope import TaskScope

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioPlayChimeAction
from ubo_app.store.services.infrared import InfraredSendCodeAction
from ubo_app.store.services.notifications import (
    Chime,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.rgb_ring import (
    RgbRingBlankAction,
    RgbRingSetAllAction,
    RgbRingSetBrightnessAction,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.main import UboAction
    from ubo_app.store.services.infrared import InfraredState

NOTIFICATION_ID = 'mqtt:notify'
RGB_MAX = 255
DEFAULT_NOTIFICATION_COLOR = '#ffffff'
_COLOR_PATTERN = re.compile(r'#[0-9a-fA-F]{6}')

# Exactly what a rich notification may set. Anything else is refused rather
# than ignored — `Notification.actions` in particular must stay unreachable.
_NOTIFY_RICH_FIELDS = frozenset(
    {'title', 'message', 'chime', 'display_type', 'blink', 'color', 'icon'},
)

# The delayed ring flush lives here. Closed by `init_service`'s subscriptions.
SCOPE = TaskScope('mqtt:commands')


class CommandError(Exception):
    """The payload is not something this command can act on."""


class Command(NamedTuple):
    """One thing Home Assistant may ask the pod to do."""

    name: str
    label: str
    parse: Callable[[str], UboAction]


def _parse_notify(payload: str) -> UboAction:
    """Home Assistant's `notify` platform publishes the raw message text.

    No `command_template` is declared, so there is no title to read — the docs
    do not specify which variables such a template gets, and guessing produces
    an entity that silently never works.
    """
    message = payload.strip()
    if not message:
        msg = 'an empty notification'
        raise CommandError(msg)
    return NotificationsAddAction(
        # Built field by field from scalars, never from a caller-supplied
        # `Notification`. `Notification.actions` can carry a
        # `NotificationDispatchItem(store_action=...)`, i.e. an arbitrary action
        # fired when the user presses a button — constructing it here makes that
        # unreachable rather than merely discouraged.
        notification=Notification(
            id=NOTIFICATION_ID,
            title='Home Assistant',
            content=message[:MAX_NOTIFICATION_MESSAGE],
            display_type=NotificationDisplayType.FLASH,
        ),
    )


def _bounded_text(raw: object, key: str, limit: int) -> str:
    """Read one bounded string field out of a rich-notification payload."""
    if not isinstance(raw, str):
        msg = f'{key} must be a string'
        raise CommandError(msg)
    return raw.strip()[:limit]


def _parse_notify_rich(payload: str) -> UboAction:
    """Everything `notify.send_message` cannot carry.

    Home Assistant's notify *entity* action takes a message and a title and
    nothing else — no arbitrary data dict — so chime, ring blink, colour and
    flash-vs-sticky need a topic of their own, driven from an automation with
    `mqtt.publish`. Same shape as `ring.color`.

    Every field is read explicitly and unknown ones are refused: the point is
    that a caller still cannot reach `Notification.actions`, which would let it
    smuggle an arbitrary action onto a button press.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exception:
        msg = 'not valid JSON'
        raise CommandError(msg) from exception
    if not isinstance(data, dict):
        msg = 'expected a JSON object'
        raise CommandError(msg)

    unknown = set(data) - _NOTIFY_RICH_FIELDS
    if unknown:
        msg = f'unknown field(s): {", ".join(sorted(unknown))}'
        raise CommandError(msg)

    message = _bounded_text(data.get('message'), 'message', MAX_NOTIFICATION_MESSAGE)
    if not message:
        msg = 'an empty notification'
        raise CommandError(msg)

    chime = data.get('chime')
    if chime is not None and chime not in tuple(Chime):
        msg = f'unknown chime {chime!r}'
        raise CommandError(msg)

    display_type = data.get('display_type', NotificationDisplayType.FLASH)
    if display_type not in tuple(NotificationDisplayType):
        msg = f'unknown display_type {display_type!r}'
        raise CommandError(msg)

    blink = data.get('blink', True)
    if not isinstance(blink, bool):
        msg = 'blink must be true or false'
        raise CommandError(msg)

    color = data.get('color', DEFAULT_NOTIFICATION_COLOR)
    if not isinstance(color, str) or not _COLOR_PATTERN.fullmatch(color):
        msg = f'color must look like #rrggbb, got {color!r}'
        raise CommandError(msg)

    notification = Notification(
        id=NOTIFICATION_ID,
        title=_bounded_text(
            data.get('title', 'Home Assistant'),
            'title',
            MAX_NOTIFICATION_TITLE,
        ),
        content=message,
        display_type=NotificationDisplayType(display_type),
        chime=Chime(chime) if chime is not None else None,
        blink=blink,
        color=color,
    )
    # Only set when the payload carries one: `Notification` derives its default
    # icon from the importance, and always passing `icon=` — even empty — would
    # override that with a blank.
    if 'icon' in data:
        notification = replace(
            notification,
            icon=_bounded_text(data.get('icon'), 'icon', MAX_NOTIFICATION_ICON),
        )
    return NotificationsAddAction(notification=notification)


def _parse_chime(payload: str) -> UboAction:
    """Read the bare option string a `select` publishes, e.g. `done`."""
    name = payload.strip().lower()
    if name not in tuple(Chime):
        msg = f'unknown chime {name!r}'
        raise CommandError(msg)
    return AudioPlayChimeAction(name=name)


def _parse_brightness(payload: str) -> UboAction:
    """Read the bare number a `number` publishes, e.g. `0.55`."""
    try:
        brightness = float(payload.strip())
    except ValueError as exception:
        msg = f'{payload.strip()!r} is not a number'
        raise CommandError(msg) from exception
    # Checked here rather than left to the reducer: `as_command()` *raises* on an
    # out-of-range brightness, and an exception inside the reducer chain is a far
    # worse outcome than a rejected command.
    if not 0 <= brightness <= 1:
        msg = f'brightness {brightness} is outside 0..1'
        raise CommandError(msg)
    return RgbRingSetBrightnessAction(brightness=brightness)


def _parse_ring_off(_: str) -> UboAction:
    """Blank the ring. A `button` payload is `payload_press` and means nothing."""
    return RgbRingBlankAction()


def _channel(raw: object, key: str) -> int:
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        msg = f'{key} must be a number'
        raise CommandError(msg)
    # Python's JSON parser accepts `NaN` and `Infinity`, and `int()` on either
    # raises — `ValueError` and `OverflowError` respectively — straight past the
    # `CommandError` boundary that `dispatch` promises never to cross.
    if not math.isfinite(raw):
        msg = f'{key} must be a finite number'
        raise CommandError(msg)
    value = int(raw)
    if not 0 <= value <= RGB_MAX:
        msg = f'{key} is outside 0..{RGB_MAX}'
        raise CommandError(msg)
    return value


def _parse_ring_color(payload: str) -> UboAction:
    """Driven from an automation, so this one really is JSON.

    Only numeric channels are accepted. `as_command()` interpolates these into a
    string that the rgb-ring service then splits on whitespace, so a string
    channel would let a caller inject extra command tokens.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exception:
        msg = 'not valid JSON'
        raise CommandError(msg) from exception
    if not isinstance(data, dict):
        msg = 'expected a JSON object with r, g and b'
        raise CommandError(msg)
    return RgbRingSetAllAction(
        color=(
            _channel(data.get('r'), 'r'),
            _channel(data.get('g'), 'g'),
            _channel(data.get('b'), 'b'),
        ),
    )


@store.with_state(lambda state: state.mqtt.allow_remote_control)
def _remote_control_allowed(allow_remote_control: bool) -> bool:  # noqa: FBT001
    return allow_remote_control


@store.with_state(lambda state: getattr(state, 'infrared', None))
def _registered_codes(infrared_state: InfraredState | None) -> set[str]:
    # The infrared service can be disabled, and then the slice simply does not
    # exist — `state.infrared` raises rather than returning None.
    if infrared_state is None:
        return set()
    return {
        f'{device.protocol}:{device.scancode}'
        for device in infrared_state.registered_devices
    }


def _parse_ir_send(payload: str) -> UboAction:
    """Send a code the pod already knows, identified as `protocol:scancode`.

    An **allowlist**, deliberately: a remote caller cannot ask the pod to emit
    an arbitrary infrared code, only one of the codes the user registered on the
    device. Each Home Assistant button carries its own code as `payload_press`,
    so this is the same value round-tripping back.
    """
    identifier = payload.strip()
    if identifier not in _registered_codes():
        msg = f'{identifier!r} is not a registered infrared device'
        raise CommandError(msg)
    protocol, _, scancode = identifier.partition(':')
    return InfraredSendCodeAction(protocol=protocol, scancode=scancode)


COMMANDS: tuple[Command, ...] = (
    Command(name='notify', label='Notification', parse=_parse_notify),
    Command(name='chime', label='Chime', parse=_parse_chime),
    Command(name='ring.brightness', label='Ring Brightness', parse=_parse_brightness),
    Command(name='ring.off', label='Ring Off', parse=_parse_ring_off),
    Command(name='ring.color', label='Ring Colour', parse=_parse_ring_color),
    Command(name='ir.send', label='Infrared', parse=_parse_ir_send),
    Command(
        name='notify.rich',
        label='Notification (with options)',
        parse=_parse_notify_rich,
    ),
)

_BY_NAME = {command.name: command for command in COMMANDS}

# Rate state, module-level rather than in the store: a counter in state would
# make the all-services golden snapshot flaky, and none of it is worth
# persisting.
_recent_notifications: list[float] = []
_last_chime = 0.0
_last_ring = 0.0
_last_ir_send = 0.0
# The newest ring action seen inside the current interval, and the timer that
# will flush it. See `_coalesce_ring`.
_pending_ring: UboAction | None = None
_ring_flush: asyncio.Task[None] | None = None


def _allow_chime(now: float) -> bool:
    global _last_chime  # noqa: PLW0603
    if now - _last_chime < 1:
        return False
    _last_chime = now
    return True


def _allow_notification(now: float) -> bool:
    _recent_notifications[:] = [
        stamp for stamp in _recent_notifications if now - stamp < NOTIFY_RATE_WINDOW
    ]
    if len(_recent_notifications) >= NOTIFY_RATE_BURST:
        return False
    _recent_notifications.append(now)
    return True


def _coalesce_ring(action: UboAction, now: float) -> None:
    """Rate-limit ring updates *without* losing the value that matters.

    Dragging a Home Assistant slider produces a burst, and the last value is the
    one the user meant. A plain throttle would drop exactly that one and leave
    the ring on an intermediate colour, so instead the newest action is held and
    flushed on a trailing timer: at most one dispatch per interval, and the final
    value always lands.
    """
    global _pending_ring, _ring_flush  # noqa: PLW0603

    _pending_ring = action
    if now - _last_ring >= RING_COALESCE_INTERVAL:
        _flush_ring()
        return
    if _ring_flush is None or _ring_flush.done():
        # Owned by the service's scope rather than detached: this is a *delayed*
        # task, so a bare `asyncio.create_task` would keep running — and could
        # still dispatch — after the service had stopped. The scope also holds a
        # reference, which is what stops it being collected mid-sleep.
        _ring_flush = SCOPE.create(
            _flush_ring_later(RING_COALESCE_INTERVAL),
            name='mqtt:ring-flush',
        )


def _flush_ring() -> None:
    """Dispatch whatever ring action is pending, if any.

    Consent is re-checked here, not just at the door: the flush runs on a
    detached timer, so the user can switch Home Assistant control off in the
    gap between a command arriving and its trailing flush firing.
    """
    global _last_ring, _pending_ring  # noqa: PLW0603
    if _pending_ring is None:
        return
    action, _pending_ring = _pending_ring, None
    _last_ring = time.monotonic()
    if not _remote_control_allowed():
        logger.debug('MQTT: dropping a pending ring update, control was disabled')
        return
    store.dispatch(action)


async def _flush_ring_later(delay: float) -> None:
    """Flush the newest ring action once the interval is up.

    Nothing needs cancelling if the pending value is cleared in the meantime —
    `_flush_ring` is a no-op with nothing pending.
    """
    await asyncio.sleep(delay)
    _flush_ring()


def _allow_ir_send(now: float) -> bool:
    """Bound infrared sends.

    `090-infrared`'s send queue is unbounded and each send shells out to
    `ir-ctl` behind a lock, so an unthrottled button is a queue-flooding vector.
    Half a second still allows normal repeat presses.
    """
    global _last_ir_send  # noqa: PLW0603
    if now - _last_ir_send < IR_SEND_MIN_INTERVAL:
        return False
    _last_ir_send = now
    return True


def _is_allowed(name: str, now: float) -> bool:
    """Whether a one-shot command may run now. Ring updates are not one-shot."""
    if name == 'chime':
        return _allow_chime(now)
    if name.startswith('notify'):
        return _allow_notification(now)
    if name == 'ir.send':
        return _allow_ir_send(now)
    return True


def reset_rate_limits() -> None:
    """Forget every rate-limit window and drop any pending flush. For tests."""
    global _last_chime, _last_ir_send, _last_ring  # noqa: PLW0603
    global _pending_ring, _ring_flush  # noqa: PLW0603
    _recent_notifications.clear()
    _last_chime = 0.0
    _last_ir_send = 0.0
    _last_ring = 0.0
    _pending_ring = None
    if _ring_flush is not None and not _ring_flush.done():
        _ring_flush.cancel()
    _ring_flush = None


@store.with_state(lambda state: state.mqtt.allow_remote_control)
def dispatch(
    allow_remote_control: bool,  # noqa: FBT001
    name: str,
    payload: bytes,
) -> str | None:
    """Act on one inbound command. Returns None, or why it was refused.

    Never raises: it runs inside the bridge's message loop, and an escaping
    exception there used to take the whole bridge down until a restart.
    """
    if not allow_remote_control:
        return 'remote control is off'

    command = _BY_NAME.get(name)
    if command is None:
        return f'unknown command {name!r}'

    if len(payload) > MAX_COMMAND_PAYLOAD:
        return f'payload is {len(payload)} bytes'

    if not _is_allowed(name, time.monotonic()):
        return 'rate limited'

    try:
        text = payload.decode()
    except UnicodeDecodeError:
        return 'payload is not text'

    try:
        action = command.parse(text)
        logger.debug('MQTT: running a command', extra={'command': name})
        if name.startswith('ring.'):
            _coalesce_ring(action, time.monotonic())
        else:
            store.dispatch(action)
    except CommandError as exception:
        return str(exception)
    # The "never raises" contract above, enforced: a parser reaching a store
    # slice that does not exist, or the ring flush being scheduled after
    # shutdown, must come back as a refusal, not escape into the bridge.
    except Exception:
        logger.exception('MQTT: command parser failed', extra={'command': name})
        return 'the command failed on the pod'
    return None
