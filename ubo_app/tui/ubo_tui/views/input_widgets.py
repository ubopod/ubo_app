"""Map InputFieldType to Textual widgets and extract submitted values."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.validation import Regex
from textual.widgets import Input, MaskedInput, Select, Switch, TextArea

from ubo_tui.widgets.file_path_input import FilePathInput

if TYPE_CHECKING:
    from textual.widget import Widget

logger = logging.getLogger(__name__)


HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
DATE_TEMPLATE = "0000-00-00;0"
TIME_TEMPLATE = "00:00;0"
TRUTHY = {"True", "true", "1", "yes", "on"}


def _field_type_name(field: Any) -> str:
    """Return the field's type as an uppercase string ("TEXT", "PASSWORD", ...).

    Handles both betterproto enum instances (which have ``.name``) and plain
    strings (used in tests).
    """
    raw = getattr(field, "type", None)
    if raw is None:
        return "TEXT"
    name = getattr(raw, "name", None)
    if isinstance(name, str):
        return name.upper()
    return str(raw).upper()


def _field_options(field: Any) -> list[str]:
    """Extract option strings from an InputFieldDescription."""
    options = getattr(field, "options", None)
    if options is None:
        return []
    items = getattr(options, "items", options)
    if items is None:
        return []
    return [str(o) for o in items]


def _build_select(field: Any, default: str, validators: list[Any]) -> Widget:
    choices = _field_options(field)
    select_options = [(o, o) for o in choices]
    if select_options:
        initial = default if default in choices else select_options[0][1]
        return Select(select_options, value=initial, allow_blank=False)
    # Empty options: degrade gracefully to a text input so the form remains
    # usable rather than crashing on construction.
    return Input(value=default, validators=validators or None)


def _build_color(default: str, pattern: str) -> Widget:
    color_validators = [Regex(HEX_COLOR_PATTERN)]
    if pattern:
        color_validators.append(Regex(pattern))
    return Input(value=default, placeholder="#RRGGBB", validators=color_validators)


def _build_file(field: Any, default: str) -> Widget:
    mimetype = getattr(field, "file_mimetype", None) or ""
    placeholder = (
        f"Type a path or press F2 to browse ({mimetype})"
        if mimetype
        else "Type a path or press F2 to browse"
    )
    return FilePathInput(
        value=default,
        placeholder=placeholder,
        title=getattr(field, "label", "") or "Select a file",
    )


def build_widget(field: Any) -> Widget:
    """Create a Textual widget for the given InputFieldDescription."""
    field_type = _field_type_name(field)
    default = getattr(field, "default_value", "") or ""
    pattern = getattr(field, "pattern", None) or ""
    validators: list[Any] = [Regex(pattern)] if pattern else []

    simple_builders: dict[str, Any] = {
        "PASSWORD": lambda: Input(
            value=default,
            password=True,
            validators=validators or None,
        ),
        "NUMBER": lambda: Input(
            value=default,
            type="number",
            validators=validators or None,
        ),
        "LONG": lambda: TextArea(text=default),
        "CHECKBOX": lambda: Switch(value=default in TRUTHY),
        "DATE": lambda: MaskedInput(
            template=DATE_TEMPLATE,
            value=default,
            validators=validators or None,
        ),
        "TIME": lambda: MaskedInput(
            template=TIME_TEMPLATE,
            value=default,
            validators=validators or None,
        ),
    }
    if field_type in simple_builders:
        return simple_builders[field_type]()
    if field_type == "SELECT":
        return _build_select(field, default, validators)
    if field_type == "COLOR":
        return _build_color(default, pattern)
    if field_type == "FILE":
        return _build_file(field, default)
    # TEXT and any unknown type fall through to a plain text input.
    return Input(value=default, validators=validators or None)


def widget_value(widget: Widget) -> str:
    """Read a string value out of a widget produced by build_widget."""
    if isinstance(widget, Switch):
        return "True" if widget.value else "False"
    if isinstance(widget, TextArea):
        return widget.text
    if isinstance(widget, Select):
        value = widget.value
        return "" if value is None or value is Select.BLANK else str(value)
    if isinstance(widget, (FilePathInput, Input, MaskedInput)):
        return widget.value
    # Defensive fallback for unknown widget types.
    return str(getattr(widget, "value", ""))


def _file_field_path(widget: Widget) -> Path | None:
    if isinstance(widget, FilePathInput):
        return widget.get_path()
    text = widget_value(widget).strip()
    return Path(text).expanduser() if text else None


def _file_field_is_valid(widget: Widget, *, required: bool) -> bool:
    path = _file_field_path(widget)
    if path is None:
        return not required
    try:
        return path.is_file()
    except OSError:
        return False


def widget_is_valid(widget: Widget, field: Any) -> bool:
    """Check required + Textual validators for a widget/field pair."""
    field_type = _field_type_name(field)
    required = bool(getattr(field, "required", False))

    if field_type in {"CHECKBOX", "SELECT"}:
        # Switch always has a boolean; Select always returns the chosen value.
        return True

    if field_type == "FILE":
        return _file_field_is_valid(widget, required=required)

    value = widget_value(widget)
    if required and not value.strip():
        return False
    return not (
        isinstance(widget, (Input, MaskedInput))
        and not getattr(widget, "is_valid", True)
    )
