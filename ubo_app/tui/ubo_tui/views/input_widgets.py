"""Map InputFieldType to Textual widgets and extract submitted values."""

from __future__ import annotations

import logging
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


def build_widget(field: Any) -> Widget:
    """Create a Textual widget for the given InputFieldDescription.

    Returns an FILE placeholder for FILE fields; the actual file path
    composite widget is provided by Phase 3 and is not wired here yet.
    """
    field_type = _field_type_name(field)
    default = getattr(field, "default_value", "") or ""
    pattern = getattr(field, "pattern", None) or ""
    validators: list[Any] = []
    if pattern:
        validators.append(Regex(pattern))

    if field_type == "PASSWORD":
        return Input(value=default, password=True, validators=validators or None)

    if field_type == "NUMBER":
        return Input(value=default, type="number", validators=validators or None)

    if field_type == "LONG":
        return TextArea(text=default)

    if field_type == "CHECKBOX":
        return Switch(value=default in TRUTHY)

    if field_type == "SELECT":
        choices = _field_options(field)
        # Each option is shown to the user and submitted as the same string
        select_options = [(o, o) for o in choices]
        if select_options:
            initial = default if default in choices else select_options[0][1]
            return Select(select_options, value=initial, allow_blank=False)
        # Empty options: degrade gracefully to a text input so the form
        # remains usable rather than crashing on construction.
        return Input(value=default, validators=validators or None)

    if field_type == "COLOR":
        color_validators = [Regex(HEX_COLOR_PATTERN)]
        if pattern:
            color_validators.append(Regex(pattern))
        return Input(
            value=default,
            placeholder="#RRGGBB",
            validators=color_validators,
        )

    if field_type == "DATE":
        return MaskedInput(
            template=DATE_TEMPLATE,
            value=default,
            validators=validators or None,
        )

    if field_type == "TIME":
        return MaskedInput(
            template=TIME_TEMPLATE,
            value=default,
            validators=validators or None,
        )

    if field_type == "FILE":
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
        if value is None or value is Select.BLANK:
            return ""
        return str(value)
    if isinstance(widget, FilePathInput):
        return widget.value
    if isinstance(widget, (Input, MaskedInput)):
        return widget.value
    # Defensive fallback for unknown widget types.
    return str(getattr(widget, "value", ""))


def widget_is_valid(widget: Widget, field: Any) -> bool:
    """Check required + Textual validators for a widget/field pair."""
    field_type = _field_type_name(field)
    required = bool(getattr(field, "required", False))

    if field_type in {"CHECKBOX", "SELECT"}:
        # Switch always has a boolean; Select always returns the chosen value.
        return True

    if field_type == "FILE":
        # File fields validate by checking that the path exists and is a
        # readable regular file when required. An empty path is fine for
        # optional fields.
        if isinstance(widget, FilePathInput):
            path = widget.get_path()
        else:
            text = widget_value(widget).strip()
            from pathlib import Path  # local import to keep top tidy

            path = Path(text).expanduser() if text else None

        if path is None:
            return not required
        try:
            return path.is_file()
        except OSError:
            return False

    value = widget_value(widget)

    if required and not value.strip():
        return False

    if isinstance(widget, (Input, MaskedInput)):
        # Textual exposes the live validation state via Input.is_valid.
        is_valid = getattr(widget, "is_valid", True)
        if not is_valid:
            return False

    return True
