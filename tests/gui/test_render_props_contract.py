"""The Kivy client splats a render view's props into the widget constructor.

Every other client reads props by name and ignores the rest, so the core is free
to add a prop for one client only — `readings` gained `keys` and
`device_classes` so the iOS/Android detail views could look up the same
icon+range table the Dashboard tiles use. Kivy instead *raises* on a kwarg it
has no property for, and `_render_view` swallows the exception, so the sensor's
readings page silently never opened on the pod screen while every other client
showed it. `_accepted_kwargs` is the only thing standing between the two.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from kivy.event import EventDispatcher
from kivy.properties import ListProperty

# Same import arrangement as `test_view_renderer_frame_stream.py`: the GUI
# client's modules import each other as `ubo_gui_client.*`.
_GUI_ROOT = str(Path(__file__).resolve().parents[2] / 'ubo_app' / 'gui')
if _GUI_ROOT not in sys.path:
    sys.path.insert(0, _GUI_ROOT)

from ubo_app.gui.ubo_gui_client.view_renderer import _accepted_kwargs  # noqa: E402

# What `040-sensors/menu.py` puts in a `readings` view's props.
READINGS_PROPS: dict[str, object] = {
    'labels': ['Temperature'],
    'values': ['22.5'],
    'units': ['°C'],
    'keys': ['temperature'],
    'device_classes': ['temperature'],
}


def test_kivy_rejects_a_kwarg_it_has_no_property_for() -> None:
    """The behavior the filter exists for — pinned, because it is not obvious."""

    class _Probe(EventDispatcher):
        labels = ListProperty()

    with pytest.raises(TypeError, match='may not be existing property names'):
        _Probe(labels=[], keys=[])


def test_the_readings_widget_accepts_every_prop_the_core_sends() -> None:
    """Post-filter, nothing is left that would make the constructor raise."""
    from ubo_app.gui.ubo_gui_client.widgets.readings import ReadingsRenderPage

    accepted = _accepted_kwargs(ReadingsRenderPage, READINGS_PROPS)

    assert all(hasattr(ReadingsRenderPage, key) for key in accepted)


def test_the_readings_widget_still_gets_the_props_it_renders() -> None:
    """Filtering must not throw away the table itself."""
    from ubo_app.gui.ubo_gui_client.widgets.readings import ReadingsRenderPage

    accepted = _accepted_kwargs(ReadingsRenderPage, READINGS_PROPS)

    assert set(accepted) >= {'labels', 'values', 'units'}
