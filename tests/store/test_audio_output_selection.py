"""Playback output selection: volume memory and lineout jack auto-switching.

``Ubo Speakers`` and ``Lineout`` are the same PipeWire sink driven through two
independent analog amps, so switching between them is a mixer change, not a
sink change — but from the store's point of view they are simply two of the
four outputs, each with its own remembered level.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from tests.service_loader import load_service_modules

if TYPE_CHECKING:
    from redux import BaseAction

    from ubo_app.store.services.audio import AudioOutput, AudioState

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/000-audio'


def _load() -> SimpleNamespace:
    """Load the audio reducer alongside its store types."""
    import importlib

    reducer, constants = load_service_modules(SERVICE_PATH, 'reducer', 'constants')
    audio = importlib.import_module('ubo_app.store.services.audio')

    return SimpleNamespace(audio=audio, reducer=reducer.reducer, constants=constants)


def _state(ns: SimpleNamespace, **kwargs: object) -> AudioState:
    return cast('AudioState', ns.audio.AudioState(**kwargs))


def _follow_up(result: object) -> list[BaseAction]:
    """Return the actions a reducer result asks to be dispatched next.

    A reducer that has nothing to follow up with returns the bare state rather
    than a ``CompleteReducerResult``, so the attribute may not be there at all.
    """
    actions = getattr(result, 'actions', None) or []
    return cast('list[BaseAction]', actions)


def _resulting_state(result: object) -> AudioState:
    """Return the state from a result that may or may not be a Complete one."""
    return cast('AudioState', getattr(result, 'state', result))


def _requested_output(result: object) -> AudioOutput:
    """Return the output of the single follow-up selection a result asks for."""
    follow_ups = _follow_up(result)
    assert len(follow_ups) == 1
    return cast('AudioOutput', follow_ups[0].output)  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.persistent_store(
    {
        'audio_state:output_volumes': [
            {'output': 'lineout', 'volume': 0.25},
            {'output': 'hdmi_1', 'volume': 0.9},
        ],
    },
)
def test_restored_output_volumes_are_a_tuple() -> None:
    """A persisted value must come back as a tuple, not a list.

    ``Store.load_object`` returns a list for any JSON array regardless of the
    requested ``output_type``. ``AudioState`` seeds this field at
    class-definition time and a dataclass rejects a mutable default outright,
    so a list here is fatal — and only once the key has actually been written,
    which means the first boot works and every boot after it fails to import
    the module at all, taking the whole app down.
    """
    ns = _load()

    restored = ns.audio._restore_output_volumes()  # noqa: SLF001
    assert isinstance(restored, tuple)
    assert len(restored) == 2


def test_output_volumes_is_seeded_by_a_factory() -> None:
    """The field must not carry a plain default, whatever the store holds."""
    import dataclasses

    ns = _load()
    field = next(
        f
        for f in dataclasses.fields(ns.audio.AudioState)
        if f.name == 'output_volumes'
    )

    assert field.default is dataclasses.MISSING
    assert field.default_factory is not dataclasses.MISSING
    assert isinstance(_state(ns).output_volumes, tuple)


def test_ubo_speakers_is_the_default_output() -> None:
    """A fresh state routes to the HAT, never to HDMI."""
    ns = _load()

    assert _state(ns).selected_output == ns.audio.AudioOutput.UBO_SPEAKERS


def test_each_output_remembers_its_own_volume() -> None:
    """Switching away banks the current level; switching back restores it."""
    ns = _load()

    # Speakers at 0.8, then move to lineout and set it much lower.
    at_speakers = _state(ns, playback_volume=0.8)
    at_lineout = _resulting_state(
        ns.reducer(
            at_speakers,
            ns.audio.AudioSelectOutputAction(output=ns.audio.AudioOutput.LINEOUT),
        ),
    )
    quiet_lineout = _resulting_state(
        ns.reducer(
            at_lineout,
            ns.audio.AudioSetVolumeAction(
                volume=0.2,
                device=ns.audio.AudioDevice.OUTPUT,
            ),
        ),
    )

    back_at_speakers = _resulting_state(
        ns.reducer(
            quiet_lineout,
            ns.audio.AudioSelectOutputAction(
                output=ns.audio.AudioOutput.UBO_SPEAKERS,
            ),
        ),
    )
    assert back_at_speakers.playback_volume == 0.8

    and_back_to_lineout = _resulting_state(
        ns.reducer(
            back_at_speakers,
            ns.audio.AudioSelectOutputAction(output=ns.audio.AudioOutput.LINEOUT),
        ),
    )
    assert and_back_to_lineout.playback_volume == 0.2


def test_an_unvisited_output_inherits_the_current_volume() -> None:
    """With nothing remembered, a new output keeps the level already in use."""
    ns = _load()

    result = ns.reducer(
        _state(ns, playback_volume=0.65),
        ns.audio.AudioSelectOutputAction(output=ns.audio.AudioOutput.HDMI_2),
    )

    assert _resulting_state(result).playback_volume == 0.65


def test_inserting_a_jack_switches_to_lineout() -> None:
    """With auto-switch on, plugging in routes to the lineout."""
    ns = _load()

    result = ns.reducer(
        _state(ns, is_lineout_auto_switch_enabled=True),
        ns.audio.AudioReportLineoutJackAction(is_inserted=True),
    )

    assert _resulting_state(result).is_lineout_jack_inserted is True
    assert _requested_output(result) == ns.audio.AudioOutput.LINEOUT


def test_removing_a_jack_returns_to_the_speakers() -> None:
    """Unplugging routes back to the HAT speakers."""
    ns = _load()

    result = ns.reducer(
        _state(
            ns,
            is_lineout_auto_switch_enabled=True,
            is_lineout_jack_inserted=True,
            selected_output=ns.audio.AudioOutput.LINEOUT,
        ),
        ns.audio.AudioReportLineoutJackAction(is_inserted=False),
    )

    assert _requested_output(result) == ns.audio.AudioOutput.UBO_SPEAKERS


def test_auto_switch_off_leaves_the_output_alone() -> None:
    """The jack still gets tracked, but nothing is re-routed."""
    ns = _load()

    result = ns.reducer(
        _state(
            ns,
            is_lineout_auto_switch_enabled=False,
            selected_output=ns.audio.AudioOutput.HDMI_1,
        ),
        ns.audio.AudioReportLineoutJackAction(is_inserted=True),
    )

    state = _resulting_state(result)
    assert state.is_lineout_jack_inserted is True
    assert state.selected_output == ns.audio.AudioOutput.HDMI_1
    assert _follow_up(result) == []


def test_a_manual_pick_survives_until_the_jack_moves() -> None:
    """Choosing HDMI with headphones plugged in must stick.

    Only a *transition* re-routes, so re-reporting the level the jack is
    already at — on startup, or a repeated edge — leaves the choice alone.
    """
    ns = _load()

    plugged_in_on_hdmi = _state(
        ns,
        is_lineout_auto_switch_enabled=True,
        is_lineout_jack_inserted=True,
        selected_output=ns.audio.AudioOutput.HDMI_1,
    )

    # Same level re-reported: no change, no re-route.
    unchanged = ns.reducer(
        plugged_in_on_hdmi,
        ns.audio.AudioReportLineoutJackAction(is_inserted=True),
    )
    assert _resulting_state(unchanged).selected_output == ns.audio.AudioOutput.HDMI_1
    assert _follow_up(unchanged) == []

    # Unplugging is a real transition, so automatic switching resumes.
    unplugged = ns.reducer(
        plugged_in_on_hdmi,
        ns.audio.AudioReportLineoutJackAction(is_inserted=False),
    )
    assert _requested_output(unplugged) == ns.audio.AudioOutput.UBO_SPEAKERS


def test_enabling_auto_switch_applies_it_immediately() -> None:
    """The toggle has a visible effect rather than waiting for a plug event."""
    ns = _load()

    result = ns.reducer(
        _state(
            ns,
            is_lineout_auto_switch_enabled=False,
            is_lineout_jack_inserted=True,
            selected_output=ns.audio.AudioOutput.UBO_SPEAKERS,
        ),
        ns.audio.AudioSetLineoutAutoSwitchAction(is_enabled=True),
    )

    assert _resulting_state(result).is_lineout_auto_switch_enabled is True
    assert _requested_output(result) == ns.audio.AudioOutput.LINEOUT


def test_disabling_auto_switch_does_not_re_route() -> None:
    """Turning it off leaves the current output in place."""
    ns = _load()

    result = ns.reducer(
        _state(
            ns,
            is_lineout_auto_switch_enabled=True,
            is_lineout_jack_inserted=True,
            selected_output=ns.audio.AudioOutput.LINEOUT,
        ),
        ns.audio.AudioSetLineoutAutoSwitchAction(is_enabled=False),
    )

    state = _resulting_state(result)
    assert state.is_lineout_auto_switch_enabled is False
    assert state.selected_output == ns.audio.AudioOutput.LINEOUT
    assert _follow_up(result) == []
