"""Tests for the inbound command table.

The fixtures use the payloads **Home Assistant actually publishes**, not JSON
everywhere: a `select` sends the bare option string, a `number` sends a bare
number, a `button` sends its `payload_press`, and the `notify` platform sends the
raw message text. Getting that wrong yields an entity that appears in Home
Assistant and silently does nothing.

The store types are imported normally: `load_service_modules` leaves `ubo_app.*`
alone, so the actions the table builds and the ones asserted here are the same
classes no matter which files run together.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests.service_loader import load_service_modules
from ubo_app.store.services import (
    audio,
    infrared,
    notifications,
    rgb_ring,
    speech_synthesis,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

(commands,) = load_service_modules(
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '050-mqtt',
    'commands',
)


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """Capture what the table dispatches instead of touching the real store."""
    calls: list[Any] = []
    monkeypatch.setattr(commands.store, 'dispatch', calls.append)
    monkeypatch.setattr(
        commands.store,
        'with_state',
        lambda _selector: (lambda function: function),
    )
    # Reads the store, which has no `mqtt` slice in the unit tier.
    monkeypatch.setattr(commands, '_remote_control_allowed', lambda: True)
    commands.reset_rate_limits()
    yield calls
    commands.reset_rate_limits()


def _run(name: str, payload: bytes) -> str | None:
    """Call `dispatch` past its `with_state` wrapper, with control switched on."""
    return commands.dispatch.__wrapped__(True, name, payload)  # noqa: FBT003


def test_notify_takes_the_raw_message_text(dispatched: list[Any]) -> None:
    """The notify platform publishes the message itself, not JSON."""
    assert _run('notify', b'The kettle boiled') is None

    (action,) = dispatched
    assert isinstance(action, notifications.NotificationsAddAction)
    assert action.notification.content == 'The kettle boiled'
    assert action.notification.title == 'Home Assistant'


def test_notify_cannot_smuggle_nested_actions(dispatched: list[Any]) -> None:
    """`Notification.actions` can carry arbitrary actions to fire on a press.

    The notification is built here from scalars precisely so a remote caller
    can never populate that field.
    """
    assert _run('notify', b'{"title": "x", "actions": [{"key": "a"}]}') is None

    (action,) = dispatched
    assert list(action.notification.actions) == []
    # The JSON is treated as literal text, which is the point.
    assert action.notification.content.startswith('{')


def test_notify_rejects_an_empty_message(dispatched: list[Any]) -> None:
    """A blank flash notification tells the user nothing."""
    assert _run('notify', b'   ') == 'an empty notification'
    assert dispatched == []


def test_a_long_message_is_truncated_not_refused(dispatched: list[Any]) -> None:
    """A chatty automation should still get its notification, just bounded.

    Truncation covers messages between the display cap and the 4 KiB payload
    cap; anything above the payload cap is refused outright instead.
    """
    assert _run('notify', b'x' * 1000) is None

    (action,) = dispatched
    assert len(action.notification.content) == 256


def test_speak_takes_the_raw_message_text(dispatched: list[Any]) -> None:
    """Its own `notify` entity, so the payload is the text to say."""
    assert _run('speak', b'The kettle boiled') is None

    (action,) = dispatched
    assert isinstance(action, speech_synthesis.SpeechSynthesisReadTextAction)
    assert action.information.text == 'The kettle boiled'


def test_speak_leaves_the_engine_unset(dispatched: list[Any]) -> None:
    """Nothing here pins an engine, so the pod's selected TTS is used.

    `engine` and `speech_rate` are deprecated no-ops on the action; setting
    either would imply a choice this command deliberately does not make.
    """
    assert _run('speak', b'hello') is None

    (action,) = dispatched
    assert action.engine is None
    assert action.speech_rate is None


def test_speak_rejects_an_empty_payload(dispatched: list[Any]) -> None:
    """There is nothing to synthesize, and silence would look like a failure."""
    assert _run('speak', b'   ') == 'nothing to say'
    assert dispatched == []


def test_a_long_line_of_speech_is_truncated_not_refused(
    dispatched: list[Any],
) -> None:
    """An over-long line is still worth saying the beginning of.

    Same treatment as a notification message: truncation covers the range
    between this cap and the 4 KiB payload cap.
    """
    assert _run('speak', b'x' * 1000) is None

    (action,) = dispatched
    assert len(action.information.text) == commands.MAX_SPEAK_TEXT


def test_speech_is_rate_limited(dispatched: list[Any]) -> None:
    """Utterances overlap rather than queue, so back-to-back requests are cut."""
    assert _run('speak', b'first') is None
    assert _run('speak', b'second') == 'rate limited'

    assert len(dispatched) == 1


def test_speech_does_not_share_the_notification_budget(
    dispatched: list[Any],
) -> None:
    """Different costs, so different budgets.

    A notification is glanced at; a spoken line occupies the speaker until it
    finishes. Exhausting one must not silence the other.
    """
    for _ in range(5):
        assert _run('notify', b'hello') is None
    assert _run('notify', b'hello') == 'rate limited'

    assert _run('speak', b'still speaking') is None
    assert len(dispatched) == 6


def test_chime_takes_the_bare_option_string(dispatched: list[Any]) -> None:
    """A `select` publishes `done`, not `{"option": "done"}`."""
    assert _run('chime', b'done') is None

    (action,) = dispatched
    assert isinstance(action, audio.AudioPlayChimeAction)
    assert action.name == 'done'


def test_chime_rejects_an_unknown_option(dispatched: list[Any]) -> None:
    """Only the chimes that exist can be played."""
    assert _run('chime', b'airhorn') == "unknown chime 'airhorn'"
    assert dispatched == []


def test_brightness_takes_a_bare_number(dispatched: list[Any]) -> None:
    """A `number` publishes `0.55`, not JSON."""
    assert _run('ring.brightness', b'0.55') is None

    (action,) = dispatched
    assert isinstance(action, rgb_ring.RgbRingSetBrightnessAction)
    assert action.brightness == pytest.approx(0.55)


@pytest.mark.parametrize(
    ('payload', 'reason'),
    [
        pytest.param(b'1.5', 'brightness 1.5 is outside 0..1', id='above-range'),
        pytest.param(b'-0.2', 'brightness -0.2 is outside 0..1', id='below-range'),
        pytest.param(b'bright', "'bright' is not a number", id='not-a-number'),
    ],
)
def test_brightness_is_range_checked_before_dispatch(
    payload: bytes,
    reason: str,
    dispatched: list[Any],
) -> None:
    """`as_command()` *raises* out of range, and that would run in a reducer.

    A refused command is a far better outcome than an exception inside the
    reducer chain, so the range is enforced here rather than left to the action.
    """
    assert _run('ring.brightness', payload) == reason
    assert dispatched == []


def test_ring_off_ignores_the_button_payload(dispatched: list[Any]) -> None:
    """A `button` publishes `payload_press`; its value carries no meaning."""
    assert _run('ring.off', b'PRESS') is None

    (action,) = dispatched
    assert isinstance(action, rgb_ring.RgbRingBlankAction)


def test_ring_colour_takes_json(dispatched: list[Any]) -> None:
    """Colour has no stock entity, so it is driven from an automation."""
    assert _run('ring.color', b'{"r": 255, "g": 0, "b": 128}') is None

    (action,) = dispatched
    assert isinstance(action, rgb_ring.RgbRingSetAllAction)
    assert action.color == (255, 0, 128)


@pytest.mark.parametrize(
    ('payload', 'reason'),
    [
        pytest.param(b'not json', 'not valid JSON', id='not-json'),
        pytest.param(
            b'[255, 0, 0]',
            'expected a JSON object with r, g and b',
            id='array',
        ),
        pytest.param(b'{"r": 255, "g": 0}', 'b must be a number', id='missing-channel'),
        pytest.param(
            b'{"r": 300, "g": 0, "b": 0}',
            'r is outside 0..255',
            id='out-of-range',
        ),
        pytest.param(
            b'{"r": "0 extra", "g": 0, "b": 0}',
            'r must be a number',
            id='string-channel',
        ),
        pytest.param(
            b'{"r": NaN, "g": 0, "b": 0}',
            'r must be a finite number',
            id='nan',
        ),
        pytest.param(
            b'{"r": Infinity, "g": 0, "b": 0}',
            'r must be a finite number',
            id='infinity',
        ),
        pytest.param(
            b'{"r": 1e999, "g": 0, "b": 0}',
            'r must be a finite number',
            id='overflows-to-infinity',
        ),
    ],
)
def test_ring_colour_rejects_bad_payloads(
    payload: bytes,
    reason: str,
    dispatched: list[Any],
) -> None:
    """A string channel would inject extra tokens.

    `as_command()` interpolates the channels into a string that the rgb-ring
    service then splits on whitespace.
    """
    assert _run('ring.color', payload) == reason
    assert dispatched == []


def test_control_off_refuses_everything(dispatched: list[Any]) -> None:
    """The master switch is checked before anything is parsed."""
    assert commands.dispatch.__wrapped__(False, 'chime', b'done') == (  # noqa: FBT003
        'remote control is off'
    )
    assert dispatched == []


def test_an_unknown_command_is_refused(dispatched: list[Any]) -> None:
    """The table is an allowlist, not a dispatcher for arbitrary names."""
    assert _run('power.off', b'') == "unknown command 'power.off'"
    assert dispatched == []


def test_an_oversized_payload_is_refused_before_parsing(
    dispatched: list[Any],
) -> None:
    """Bounded before `json.loads` ever sees it."""
    assert _run('ring.color', b'{"r":0,"g":0,"b":0}' + b' ' * 5000) == (
        'payload is 5019 bytes'
    )
    assert dispatched == []


def test_a_non_utf8_payload_is_refused(dispatched: list[Any]) -> None:
    """Bytes off the wire are not guaranteed to be text."""
    assert _run('notify', b'\xff\xfe') == 'payload is not text'
    assert dispatched == []


def _registered(codes: set[str]) -> Callable[[], set[str]]:
    """Stand in for the store-backed registry lookup."""
    return lambda: codes


def test_ir_send_resolves_a_registered_device(
    dispatched: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each Home Assistant button sends back the identifier it was given."""
    monkeypatch.setattr(commands, '_registered_codes', _registered({'nec:0x40'}))

    assert _run('ir.send', b'nec:0x40') is None

    (action,) = dispatched
    assert isinstance(action, infrared.InfraredSendCodeAction)
    assert (action.protocol, action.scancode) == ('nec', '0x40')


def test_ir_send_refuses_an_unregistered_code(
    dispatched: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the identifier: this is an allowlist.

    A remote caller must not be able to make the pod emit an arbitrary infrared
    code — only one the user registered on the device.
    """
    monkeypatch.setattr(commands, '_registered_codes', _registered({'nec:0x40'}))

    assert _run('ir.send', b'sony:0xdeadbeef') == (
        "'sony:0xdeadbeef' is not a registered infrared device"
    )
    assert dispatched == []


def test_ir_send_refuses_when_the_infrared_service_is_missing(
    dispatched: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`dispatch` promises to never raise, and the slice can be absent.

    `state.infrared` raises `AttributeError` while the infrared service is
    disabled; that has to come back as a refusal, not escape into the bridge's
    message loop.
    """

    def _missing_slice() -> set[str]:
        raise AttributeError(commands.__name__)

    monkeypatch.setattr(commands, '_registered_codes', _missing_slice)

    assert _run('ir.send', b'nec:0x40') == 'the command failed on the pod'
    assert dispatched == []


def test_a_missing_infrared_slice_registers_no_codes() -> None:
    """The guarded selector hands None over; that reads as an empty allowlist."""
    assert commands._registered_codes.__wrapped__(None) == set()  # noqa: SLF001


def test_ir_send_is_rate_limited(
    dispatched: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`090-infrared`'s send queue is unbounded and each send shells out.

    An unthrottled button would be a queue-flooding vector.
    """
    monkeypatch.setattr(commands, '_registered_codes', _registered({'nec:0x40'}))

    assert _run('ir.send', b'nec:0x40') is None
    assert _run('ir.send', b'nec:0x40') == 'rate limited'

    assert len(dispatched) == 1


def test_chimes_are_rate_limited(dispatched: list[Any]) -> None:
    """A flood of chimes must not turn the pod into an alarm."""
    assert _run('chime', b'done') is None
    assert _run('chime', b'add') == 'rate limited'

    assert len(dispatched) == 1


def test_notifications_allow_a_burst_then_stop(dispatched: list[Any]) -> None:
    """Bursts are normal; a sustained flood is not."""
    for _ in range(5):
        assert _run('notify', b'hello') is None
    assert _run('notify', b'hello') == 'rate limited'

    assert len(dispatched) == 5


async def test_a_pending_ring_update_is_dropped_if_consent_is_withdrawn(
    dispatched: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trailing flush runs on a detached timer.

    The user can switch Home Assistant control off in the gap between a command
    arriving and its flush firing, so consent is re-checked at the flush, not
    only at the door.
    """
    assert _run('ring.brightness', b'0.1') is None
    assert _run('ring.brightness', b'0.9') is None
    assert len(dispatched) == 1

    monkeypatch.setattr(commands, '_remote_control_allowed', lambda: False)
    await asyncio.sleep(commands.RING_COALESCE_INTERVAL * 3)

    assert len(dispatched) == 1


async def test_ring_updates_coalesce_to_the_newest_value(
    dispatched: list[Any],
) -> None:
    """A slider drag must end on the value the user released at.

    Plain throttling would drop exactly that one and leave the ring on an
    intermediate colour, so the newest action is held and flushed on a trailing
    timer instead.
    """
    for level in ('0.1', '0.2', '0.3', '0.9'):
        assert _run('ring.brightness', level.encode()) is None

    # The first lands immediately; the rest collapse into one trailing flush.
    assert len(dispatched) == 1
    await asyncio.sleep(commands.RING_COALESCE_INTERVAL * 3)

    assert len(dispatched) == 2
    assert dispatched[-1].brightness == pytest.approx(0.9)


def test_notify_rich_carries_the_options_send_message_cannot(
    dispatched: list[Any],
) -> None:
    """Home Assistant's notify action takes a message and a title, nothing else.

    Chime, ring blink, colour and flash-vs-sticky need a topic of their own —
    the pod already drives all of them off the notification's own fields.
    """
    assert (
        _run(
            'notify.rich',
            b'{"title": "Doorbell", "message": "Someone is at the door",'
            b' "chime": "add", "display_type": "sticky", "blink": true,'
            b' "color": "#ff3f51", "icon": "\xf3\xb0\x8b\x8f"}',
        )
        is None
    )

    (action,) = dispatched
    notification = action.notification
    assert notification.title == 'Doorbell'
    assert notification.content == 'Someone is at the door'
    assert notification.chime is notifications.Chime.ADD
    assert notification.display_type is notifications.NotificationDisplayType.STICKY
    assert notification.blink is True
    assert notification.color == '#ff3f51'


def test_notify_rich_defaults_are_a_plain_flash(dispatched: list[Any]) -> None:
    """Only `message` is required; the rest behave like the simple command."""
    assert _run('notify.rich', b'{"message": "hi"}') is None

    (action,) = dispatched
    assert action.notification.title == 'Home Assistant'
    assert action.notification.chime is None
    assert (
        action.notification.display_type
        is notifications.NotificationDisplayType.FLASH
    )


def test_notify_rich_without_an_icon_keeps_the_default(
    dispatched: list[Any],
) -> None:
    """`Notification` derives its default icon from the importance.

    Passing `icon=''` for an absent key would override that derivation with a
    blank, so the field is only set when the payload actually carries one.
    """
    assert _run('notify.rich', b'{"message": "Doorbell"}') is None

    (action,) = dispatched
    assert action.notification.icon != ''


def test_notify_rich_still_cannot_smuggle_actions(dispatched: list[Any]) -> None:
    """The whole reason every field is read explicitly.

    `Notification.actions` can carry a nested store action fired on a button
    press, so an unknown field is refused rather than passed through.
    """
    assert _run(
        'notify.rich',
        b'{"message": "hi", "actions": [{"key": "a"}]}',
    ) == 'unknown field(s): actions'
    assert dispatched == []


@pytest.mark.parametrize(
    ('payload', 'reason'),
    [
        pytest.param(b'not json', 'not valid JSON', id='not-json'),
        pytest.param(b'["hi"]', 'expected a JSON object', id='array'),
        pytest.param(b'{"message": "  "}', 'an empty notification', id='empty'),
        pytest.param(
            b'{"message": "hi", "chime": "airhorn"}',
            "unknown chime 'airhorn'",
            id='bad-chime',
        ),
        pytest.param(
            b'{"message": "hi", "display_type": "loud"}',
            "unknown display_type 'loud'",
            id='bad-display-type',
        ),
        pytest.param(
            b'{"message": "hi", "blink": "yes"}',
            'blink must be true or false',
            id='bad-blink',
        ),
        pytest.param(
            b'{"message": "hi", "color": "red"}',
            "color must look like #rrggbb, got 'red'",
            id='bad-color',
        ),
        pytest.param(
            b'{"message": 4}',
            'message must be a string',
            id='non-string-message',
        ),
    ],
)
def test_notify_rich_rejects_bad_payloads(
    payload: bytes,
    reason: str,
    dispatched: list[Any],
) -> None:
    """Every field is validated; nothing is silently coerced or ignored."""
    assert _run('notify.rich', payload) == reason
    assert dispatched == []


def test_rich_notifications_share_the_plain_notify_budget(
    dispatched: list[Any],
) -> None:
    """Same user-visible effect, so one flood limit covers both."""
    for _ in range(5):
        assert _run('notify', b'hello') is None

    assert _run('notify.rich', b'{"message": "hi"}') == 'rate limited'
    assert len(dispatched) == 5
