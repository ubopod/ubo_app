"""Modal form rendering a WebUIInputDescription."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea

from ubo_tui.upload import upload_file
from ubo_tui.views.input_widgets import (
    build_widget,
    widget_is_valid,
    widget_value,
)
from ubo_tui.widgets.file_path_input import FilePathInput

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.widget import Widget

    from ubo_tui.client import TUIClient

logger = logging.getLogger(__name__)


def _field_type_name(field: Any) -> str:
    raw = getattr(field, "type", None)
    if raw is None:
        return "TEXT"
    name = getattr(raw, "name", None)
    if isinstance(name, str):
        return name.upper()
    return str(raw).upper()


class InputForm(ModalScreen[None]):
    """Modal screen rendering a WebUIInputDescription as an editable form."""

    DEFAULT_CSS = """
    InputForm {
        align: center middle;
    }

    InputForm > Vertical {
        background: #15151f;
        border: round #5f87ff;
        width: 80%;
        max-width: 90;
        height: auto;
        max-height: 90%;
        padding: 1 2;
    }

    InputForm .form-title {
        text-style: bold;
        color: #87afff;
        margin-bottom: 1;
    }

    InputForm .form-prompt {
        margin-bottom: 1;
    }

    InputForm .field-label {
        margin-top: 1;
        text-style: bold;
    }

    InputForm .field-description {
        color: #888888;
    }

    InputForm .form-buttons {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }

    InputForm .form-buttons Button {
        margin-left: 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+s", "submit", "Submit", show=True),
    ]

    def __init__(
        self,
        description: Any,
        client: TUIClient,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._description = description
        self._client = client
        self._fields: list[Any] = self._extract_fields(description)
        self._widgets: dict[str, Widget] = {}
        self.input_id: str = getattr(description, "id", "") or ""

    @staticmethod
    def _extract_fields(description: Any) -> list[Any]:
        """Pull the list of InputFieldDescription out of the description."""
        fields = getattr(description, "fields", None)
        if fields is None:
            return []
        # betterproto wraps repeated messages in a container with `.items`
        items = getattr(fields, "items", fields)
        if items is None:
            return []
        return list(items)

    def compose(self) -> ComposeResult:
        title = getattr(self._description, "title", None) or "Input"
        prompt = getattr(self._description, "prompt", None) or ""

        with Vertical():
            yield Label(title, classes="form-title", markup=False)
            if prompt:
                yield Label(prompt, classes="form-prompt", markup=False)

            with VerticalScroll(id="form-fields"):
                if not self._fields:
                    # No structured fields: render a single text input named
                    # "value" so the user has somewhere to type.
                    widget = build_widget(_PlainField())
                    self._widgets["value"] = widget
                    yield Label("Value", classes="field-label", markup=False)
                    yield widget
                else:
                    for field in self._fields:
                        name = getattr(field, "name", "") or ""
                        label = getattr(field, "label", "") or name or "Field"
                        descr = getattr(field, "description", "") or ""

                        widget = build_widget(field)
                        self._widgets[name] = widget

                        yield Label(label, classes="field-label", markup=False)
                        if descr:
                            yield Label(
                                descr,
                                classes="field-description",
                                markup=False,
                            )
                        yield widget

            with Horizontal(classes="form-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Provide", id="provide", variant="primary")

    def on_mount(self) -> None:
        """Auto-focus the first interactive widget."""
        for widget in self._widgets.values():
            try:
                widget.focus()
            except Exception:  # noqa: BLE001
                continue
            else:
                return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "provide":
            self.action_submit()
        elif event.button.id == "cancel":
            self.action_cancel()

    def on_input_submitted(self) -> None:
        """Submit form when user presses Enter on an Input widget."""
        # Don't submit if focus is on a TextArea (Enter inserts newline there).
        focused = self.focused
        if focused is None or isinstance(focused, TextArea):
            return
        self.action_submit()

    def action_cancel(self) -> None:
        logger.info("InputForm cancel: id=%s", self.input_id)
        try:
            self._client.cancel_input(self.input_id)
        except Exception:
            logger.exception("InputForm: cancel_input dispatch failed")
        # Don't pop here: the queue subscription on app.py removes this
        # screen when the server clears the input. Pop here only if the
        # client dispatch raised; otherwise we'd race with the subscription.

    def action_submit(self) -> None:
        logger.info("InputForm submit: id=%s", self.input_id)
        # Validate every field first; bail out on the first invalid one.
        for field in self._fields:
            name = getattr(field, "name", "") or ""
            widget = self._widgets.get(name)
            if widget is None:
                continue
            if not widget_is_valid(widget, field):
                label = getattr(field, "label", "") or name or "field"
                self.app.notify(
                    f"Invalid value for '{label}'",
                    severity="error",
                )
                return

        # Walk fields once: collect non-file values directly, and for FILE
        # fields gather pending uploads and emit upload_id/name placeholders
        # into ``data`` (matching webUI inputs.tsx:232-252 contract).
        data: dict[str, str] = {}
        pending_uploads: list[tuple[str, Any]] = []  # (upload_id, path)
        for field in self._fields:
            name = getattr(field, "name", "") or ""
            widget = self._widgets.get(name)
            if widget is None:
                continue
            type_name = _field_type_name(field)
            if type_name == "FILE" and isinstance(widget, FilePathInput):
                path = widget.get_path()
                if path is None:
                    # Optional, empty FILE field — skip.
                    continue
                upload_id = uuid.uuid4().hex
                data[f"{name}_upload_id"] = upload_id
                data[f"{name}_name"] = path.name
                pending_uploads.append((upload_id, path))
            else:
                data[name] = widget_value(widget)

        if not self._fields:
            widget = self._widgets.get("value")
            if widget is not None:
                data["value"] = widget_value(widget)

        # Primary value: first non-FILE field, else "value" if present.
        primary_value = ""
        for field in self._fields:
            if _field_type_name(field) == "FILE":
                continue
            primary_value = data.get(getattr(field, "name", "") or "", "")
            break
        if not primary_value:
            primary_value = data.get("value", "")

        try:
            self._client.provide_input(self.input_id, primary_value, data)
        except Exception:
            logger.exception("InputForm: provide_input dispatch failed")
            self.app.notify("Failed to submit input", severity="error")
            return

        # Kick off chunked uploads in the background. The modal pops via the
        # queue subscription once the server processes InputProvideAction;
        # uploads continue independently and notify on completion/failure.
        for upload_id, path in pending_uploads:
            self._launch_upload(upload_id, path)

    def _launch_upload(self, upload_id: str, path: Any) -> None:
        async def _run() -> None:
            try:
                await upload_file(self._client, upload_id, path)
                self.app.notify(
                    f"Uploaded {path.name}",
                    severity="information",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Upload failed: id=%s", upload_id)
                self.app.notify(
                    f"Upload of {path.name} failed: {exc}",
                    severity="error",
                )

        asyncio.create_task(_run())


class _PlainField:
    """Minimal stand-in field used when a description has no fields list."""

    name = "value"
    label = "Value"
    type = "TEXT"
    description = None
    title = None
    file_mimetype = None
    pattern = None
    default_value = ""
    options = None
    required = False
