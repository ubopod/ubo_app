"""The audio service owns the single microphone status icon.

Only four status icons are rendered (`menu_footer.render_icons` keeps the four
highest priorities), so a second service registering its own microphone icon
pushed the real one — the lowest priority of all — off the bar entirely.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from tests.service_loader import load_service_modules

if TYPE_CHECKING:
    from redux import BaseAction, CompleteReducerResult

    from ubo_app.store.services.audio import AudioState
    from ubo_app.store.status_icons.types import StatusIconsRegisterAction

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/000-audio'

_MUTED_GLYPH = '\U000f036d'
_LIVE_GLYPH = '\U000f036c'
_GREEN = '#008000'


def _load() -> SimpleNamespace:
    """Load the audio reducer alongside its store types.

    ``ubo_app.store.services.audio`` is imported, never reloaded: the reducer
    resolves it through ``sys.modules`` too, so both sides already agree on one
    generation, and reloading it in place would swap the classes out from under
    any *other* test file that imported them at collection time.
    """
    reducer, constants = load_service_modules(SERVICE_PATH, 'reducer', 'constants')
    audio = importlib.import_module('ubo_app.store.services.audio')

    return SimpleNamespace(audio=audio, reducer=reducer.reducer, constants=constants)


def _icon(result: object) -> StatusIconsRegisterAction:
    """Return the single status-icon registration in a reducer result.

    Matched by class name: an integration test earlier in the full suite may
    have wiped ``sys.modules``, leaving the class the reducer emits a different
    generation from the one an ``isinstance`` here would test against.
    """
    actions = cast('CompleteReducerResult', result).actions or []
    icons = [
        action
        for action in cast('list[BaseAction]', actions)
        if type(action).__name__ == 'StatusIconsRegisterAction'
    ]
    assert len(icons) == 1
    return cast('StatusIconsRegisterAction', icons[0])


def _state(ns: SimpleNamespace, **kwargs: object) -> AudioState:
    return cast('AudioState', ns.audio.AudioState(**kwargs))


def test_muting_switches_the_glyph() -> None:
    """The icon reports the mute state."""
    ns = _load()

    muted = _icon(
        ns.reducer(
            _state(ns, is_capture_mute=False),
            ns.audio.AudioSetMuteStatusAction(
                is_mute=True,
                device=ns.audio.AudioDevice.INPUT,
            ),
        ),
    )
    unmuted = _icon(
        ns.reducer(
            _state(ns, is_capture_mute=True),
            ns.audio.AudioSetMuteStatusAction(
                is_mute=False,
                device=ns.audio.AudioDevice.INPUT,
            ),
        ),
    )

    assert muted.icon == _MUTED_GLYPH
    assert unmuted.icon == _LIVE_GLYPH


def test_a_remote_listener_colours_the_icon() -> None:
    """A remote client receiving the microphone turns the icon green."""
    ns = _load()

    result = ns.reducer(
        _state(ns, is_capture_mute=False),
        ns.audio.AudioReportRemoteCaptureAction(is_active=True),
    )

    icon = _icon(result)
    assert icon.color == _GREEN
    assert icon.icon == _LIVE_GLYPH
    assert result.state.is_remote_capture_active is True


def test_muting_while_remote_wins() -> None:
    """A muted microphone is never coloured as live.

    Nothing reaches a remote client while muted — the reducer emits no sample
    events — so a green microphone would claim the opposite of the truth.
    """
    ns = _load()

    result = ns.reducer(
        _state(ns, is_capture_mute=False, is_remote_capture_active=True),
        ns.audio.AudioSetMuteStatusAction(
            is_mute=True,
            device=ns.audio.AudioDevice.INPUT,
        ),
    )

    icon = _icon(result)
    assert icon.icon == _MUTED_GLYPH
    assert icon.color != _GREEN


def test_the_icon_keeps_one_identity_and_position() -> None:
    """Mute and remote-capture changes reuse one id and priority.

    A second id would be a second icon competing for the four rendered slots; a
    changing priority would move the microphone along the status bar.
    """
    ns = _load()

    icons = [
        _icon(
            ns.reducer(
                _state(ns, is_capture_mute=False),
                ns.audio.AudioSetMuteStatusAction(
                    is_mute=True,
                    device=ns.audio.AudioDevice.INPUT,
                ),
            ),
        ),
        _icon(
            ns.reducer(
                _state(ns, is_capture_mute=False),
                ns.audio.AudioReportRemoteCaptureAction(is_active=True),
            ),
        ),
        _icon(
            ns.reducer(
                _state(ns, is_capture_mute=False, is_remote_capture_active=True),
                ns.audio.AudioReportRemoteCaptureAction(is_active=False),
            ),
        ),
    ]

    assert {icon.id for icon in icons} == {ns.constants.AUDIO_MIC_STATE_ICON_ID}
    assert {icon.priority for icon in icons} == {
        ns.constants.AUDIO_MIC_STATE_ICON_PRIORITY,
    }
