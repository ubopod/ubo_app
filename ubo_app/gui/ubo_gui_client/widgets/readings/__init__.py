"""Readings render page widget.

A label/value/unit table — "Temperature    22.5 °C" — for showing a sensor's
live measurements.

The three lists are parallel: ``labels`` and ``units`` describe the rows and
change only when a different sensor is opened, while ``values`` is replaced on
every reading. So the row widgets are built once from the labels, and a new
reading only re-texts the value labels. Rebuilding the rows once a second would
churn the widget tree for nothing.

Values arrive pre-formatted as strings: rounding is the sensor registry's job
(it knows each entity's display precision), not the GUI's.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING

from kivy.lang.builder import Builder
from kivy.metrics import dp
from kivy.properties import ListProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label

from ubo_gui_client.gui_utils import UboPageWidget

if TYPE_CHECKING:
    from kivy.uix.widget import Widget

logger = logging.getLogger(__name__)

ROW_HEIGHT = 26
FONT_SIZE = 15
# The pod's screen is 240 px wide: the name gets the larger share, the value is
# right-aligned against the edge so the numbers line up down the column.
NAME_WIDTH = 0.55
VALUE_WIDTH = 0.45

UNKNOWN = '—'


def _fit_text_to_widget(widget: Label, *_: object) -> None:
    widget.text_size = widget.size


class ReadingsRenderPage(UboPageWidget):
    """A page showing a sensor's readings as a label/value/unit table."""

    labels: list[str] = ListProperty()
    values: list[str] = ListProperty()
    units: list[str] = ListProperty()
    # `PageWidget.placeholder` is `str | None` (`StringProperty(allownone=True)`);
    # a Kivy property is mutable, so the override has to keep the base's nullable
    # type rather than narrow it — only the default differs.
    placeholder: str | None = StringProperty('No readings yet', allownone=True)

    def __init__(self, **kwargs: object) -> None:
        """Initialize the page."""
        self._value_labels: list[Label] = []
        super().__init__(**kwargs)

    def on_kv_post(self, base_widget: Widget) -> None:
        """Build the rows once the kv ids exist."""
        _ = base_widget
        self._rebuild_rows()

    def on_labels(self, *_: object) -> None:
        """Rebuild the rows: a different sensor was opened."""
        self._rebuild_rows()

    def on_units(self, *_: object) -> None:
        """Rebuild the rows: a different sensor was opened."""
        self._rebuild_rows()

    def on_values(self, *_: object) -> None:
        """Re-text the existing rows. A new reading must not rebuild them."""
        self._apply_values()

    def _rebuild_rows(self) -> None:
        container = self.ids.get('rows') if self.ids else None
        if container is None:
            return

        container.clear_widgets()
        self._value_labels = []

        for label in self.labels:
            row = BoxLayout(
                orientation='horizontal',
                size_hint_y=None,
                height=dp(ROW_HEIGHT),
            )

            name_label = Label(
                text=str(label),
                halign='left',
                valign='middle',
                font_size=dp(FONT_SIZE),
                size_hint_x=NAME_WIDTH,
                shorten=True,
                shorten_from='right',
            )
            name_label.bind(size=_fit_text_to_widget)

            value_label = Label(
                text=UNKNOWN,
                halign='right',
                valign='middle',
                font_size=dp(FONT_SIZE),
                bold=True,
                size_hint_x=VALUE_WIDTH,
            )
            value_label.bind(size=_fit_text_to_widget)

            row.add_widget(name_label)
            row.add_widget(value_label)
            container.add_widget(row)
            self._value_labels.append(value_label)

        self._apply_values()

    def _apply_values(self) -> None:
        if len(self.values) > len(self.labels) or len(self.units) > len(self.labels):
            # Rows exist only for labels, so the surplus is silently dropped —
            # worth a trace: it means the core sent misaligned parallel lists.
            logger.warning(
                '[ReadingsRenderPage] values/units longer than labels '
                '(labels=%d, values=%d, units=%d); extra entries are ignored',
                len(self.labels),
                len(self.values),
                len(self.units),
            )
        for index, value_label in enumerate(self._value_labels):
            value = self.values[index] if index < len(self.values) else UNKNOWN
            unit = self.units[index] if index < len(self.units) else ''
            value_label.text = f'{value} {unit}'.strip()


Builder.load_file(
    pathlib.Path(__file__).parent.joinpath('readings.kv').resolve().as_posix(),
)
