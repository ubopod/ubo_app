"""Route playback to the selected output.

Two mechanisms, because the four outputs are not four devices:

- ``HDMI_1``/``HDMI_2`` and the HAT are separate PipeWire sinks, picked by
  setting the default sink. Everything in ubo-app opens the ALSA ``default``
  PCM, which ``libasound2-plugins`` redirects to PulseAudio, so the default
  sink is what playback *and* the volume control both follow.
- ``UBO_SPEAKERS`` and ``LINEOUT`` are the *same* sink — the WM8960 drives two
  independent analog amps off one DAC — so they are switched by selecting that
  sink's ``analog-output-speaker`` / ``analog-output-headphones`` **port**.

The port is the right lever rather than the codec's ``Speaker``/``Headphone``
mixers directly. PipeWire's ACP owns those mixers: it drives them from the sink
volume for whichever port is active and overwrites anything written behind its
back, and — the part that actually matters — selecting the port is what powers
up the corresponding output path in the codec. Setting the mixers alone leaves
the headphone amp unpowered, so the lineout stays silent.

Sinks are matched on ``alsa.card_name`` rather than PipeWire's node name: node
names embed the SoC's platform addresses and the resolved profile
(``…stereo-fallback``), both of which move between board revisions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.logger import logger
from ubo_app.store.services.audio import AudioOutput
from ubo_app.utils import IS_RPI

if TYPE_CHECKING:
    from collections.abc import Callable

_CARD_NAMES = {
    AudioOutput.UBO_SPEAKERS: 'wm8960-soundcard',
    AudioOutput.LINEOUT: 'wm8960-soundcard',
    AudioOutput.HDMI_1: 'vc4-hdmi-0',
    AudioOutput.HDMI_2: 'vc4-hdmi-1',
}

# Which of the HAT sink's two analog paths each output means. HDMI sinks have a
# single port and are absent here.
_SINK_PORTS = {
    AudioOutput.UBO_SPEAKERS: 'analog-output-speaker',
    AudioOutput.LINEOUT: 'analog-output-headphones',
}

# How long the insert-detect pin must hold a level before it is believed. The
# switch chatters as the plug slides past the contacts — measured at 15-85 ms
# of make/break on a real insertion, with the occasional ~250 ms straggler —
# and every edge restarts this clock, so one insertion yields one report of the
# settled level. Raise it if slow insertions still flicker; the only cost is
# how long a genuine plug or unplug takes to register.
_JACK_SETTLE_SECONDS = 0.3


def apply_output(output: AudioOutput) -> None:
    """Make ``output`` the active playback destination.

    Called on every selection *and* on startup, so the persisted choice is
    re-asserted over whatever port PipeWire restored on its own.
    """
    if not IS_RPI:
        return

    import pulsectl

    card_name = _CARD_NAMES[output]
    port = _SINK_PORTS.get(output)

    logger.info(
        'Audio - Applying output selection',
        extra={'output': output.value, 'card_name': card_name, 'port': port},
    )

    try:
        pulse_client = pulsectl.Pulse('ubo-audio-output')
    except pulsectl.PulseError:
        # No reachable PulseAudio/pipewire-pulse server for this session — the
        # user's PipeWire hasn't come up yet, or this is a context that has no
        # audio session at all (the on-device test runner, a bare SSH login).
        # Routing is re-asserted on every selection and at every startup, so the
        # next run applies it; failing here would report a service error on a
        # path that runs unconditionally at boot.
        logger.warning(
            'Audio - No PulseAudio server; leaving routing alone',
            extra={'output': output.value, 'card_name': card_name},
        )
        return

    with pulse_client as pulse:
        sink = next(
            (
                sink
                for sink in pulse.sink_list()
                if sink.proplist.get('alsa.card_name') == card_name
            ),
            None,
        )
        if sink is None:
            # Expected when an HDMI output is selected with no display
            # attached. PipeWire keeps the previous default, and re-selecting
            # once the display is back will find the sink.
            logger.warning(
                'Audio - No sink for the selected output; leaving routing alone',
                extra={'output': output.value, 'card_name': card_name},
            )
            return

        # Port before default: switching the port powers up the right analog
        # path, and doing it first means the sink is already routed correctly
        # by the time anything starts playing to it.
        if port is not None:
            # `port_set`, not `sink_port_set`: the latter is a raw binding that
            # wants the sink *index*, while this one takes the object.
            pulse.port_set(sink, port)
        pulse.default_set(sink)

    logger.info(
        'Audio - Output applied',
        extra={'output': output.value, 'sink': sink.name, 'port': port},
    )


def watch_lineout_jack(on_change: Callable[[bool], None]) -> Callable[[], None]:
    """Report the lineout jack's state now, and once it settles after a change.

    ``on_change`` is called once up front so a jack already in the socket at
    boot is not missed, and thereafter only when the pin has held a level for
    ``_JACK_SETTLE_SECONDS``.

    The settling timer is the whole point. Sampling at the edge instead — even
    with a debounce that suppresses the storm — reads a level that is still
    mid-bounce, and if the final edge lands inside the suppression window
    nothing ever re-reads it. That strands the selection on the wrong output
    until the jack is next touched: removing the jack leaves playback routed to
    the lineout, silently.

    Returns a callable that stops watching and releases the GPIO line.
    """
    if not IS_RPI:
        return lambda: None

    import threading

    from constants import AUDIO_LINEOUT_DETECT_PIN
    from gpiozero import Button

    # The board drives this line itself: measured high with the socket empty
    # under *both* internal bias settings, so an external pull-up dominates and
    # the socket's switch takes it to ground when a plug is seated.
    #
    # `pull_up=None` therefore leaves the internal bias disabled rather than
    # fighting that external network, and `active_state=False` keeps the sense
    # the hardware actually has — low means inserted. The two cannot be set
    # independently through `pull_up` alone: `pull_up=False` would select the
    # internal pull-down *and* silently flip the sense to active-high.
    button = Button(
        AUDIO_LINEOUT_DETECT_PIN,
        # `None` is a documented value meaning "leave the bias alone", but
        # gpiozero's stub types this parameter as a plain `bool`.
        pull_up=None,  # pyright: ignore[reportArgumentType]
        active_state=False,
    )

    lock = threading.Lock()
    settle_timer: threading.Timer | None = None

    def report_settled_level() -> None:
        # `is_active`, not the `is_pressed` alias: gpiozero assigns the latter
        # after the class body, so it is invisible to the type checker.
        on_change(button.is_active)

    def schedule_report() -> None:
        # Every edge restarts the clock, so a burst of contact chatter collapses
        # into exactly one report — taken once the pin has actually gone quiet.
        nonlocal settle_timer
        with lock:
            if settle_timer is not None:
                settle_timer.cancel()
            settle_timer = threading.Timer(
                _JACK_SETTLE_SECONDS,
                report_settled_level,
            )
            settle_timer.daemon = True
            settle_timer.start()

    button.when_pressed = schedule_report
    button.when_released = schedule_report
    report_settled_level()

    def stop_watching() -> None:
        # Drop the callbacks before closing so neither can fire against a
        # half-torn-down service, and kill any timer still counting down.
        nonlocal settle_timer
        button.when_pressed = None
        button.when_released = None
        with lock:
            if settle_timer is not None:
                settle_timer.cancel()
                settle_timer = None
        button.close()

    return stop_watching
