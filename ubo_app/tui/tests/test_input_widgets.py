"""Tests for input_widgets factory and value extraction.

Textual widgets need an active App context for their reactive watchers, so we
construct them inside ``App.run_test()`` and assert via a captured result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class _Options:
    items: list[str]


@dataclass
class _Field:
    name: str = "value"
    label: str = "Value"
    type: str = "TEXT"
    description: str | None = None
    title: str | None = None
    file_mimetype: str | None = None
    pattern: str | None = None
    default_value: str | None = ""
    options: Any = None
    required: bool = False


async def _run_in_app(callback: Any) -> Any:
    """Run ``callback`` inside a Textual app context and return its result."""
    from textual.app import App

    captured: dict[str, Any] = {}

    class _App(App[None]):
        def on_mount(self) -> None:
            captured["result"] = callback()
            self.exit()

    app = _App()
    async with app.run_test():
        pass
    return captured.get("result")


@pytest.mark.asyncio
async def test_build_text_widget_returns_input() -> None:
    from textual.widgets import Input

    from ubo_tui.views.input_widgets import build_widget

    widget = await _run_in_app(
        lambda: build_widget(_Field(type="TEXT", default_value="hello")),
    )
    assert isinstance(widget, Input)
    assert widget.value == "hello"
    assert widget.password is False


@pytest.mark.asyncio
async def test_build_password_widget_is_masked() -> None:
    from textual.widgets import Input

    from ubo_tui.views.input_widgets import build_widget

    widget = await _run_in_app(lambda: build_widget(_Field(type="PASSWORD")))
    assert isinstance(widget, Input)
    assert widget.password is True


@pytest.mark.asyncio
async def test_build_long_widget_returns_textarea() -> None:
    from textual.widgets import TextArea

    from ubo_tui.views.input_widgets import build_widget

    widget = await _run_in_app(
        lambda: build_widget(_Field(type="LONG", default_value="multi\nline")),
    )
    assert isinstance(widget, TextArea)
    assert "multi" in widget.text


@pytest.mark.asyncio
async def test_build_checkbox_widget_returns_switch() -> None:
    from textual.widgets import Switch

    from ubo_tui.views.input_widgets import build_widget

    widget_on = await _run_in_app(
        lambda: build_widget(_Field(type="CHECKBOX", default_value="True")),
    )
    assert isinstance(widget_on, Switch)
    assert widget_on.value is True

    widget_off = await _run_in_app(
        lambda: build_widget(_Field(type="CHECKBOX", default_value="False")),
    )
    assert isinstance(widget_off, Switch)
    assert widget_off.value is False


@pytest.mark.asyncio
async def test_build_select_widget_returns_select() -> None:
    from textual.app import App
    from textual.widgets import Select

    from ubo_tui.views.input_widgets import build_widget

    options = _Options(items=["a", "b", "c"])
    captured: dict[str, Any] = {}

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            widget = build_widget(
                _Field(type="SELECT", options=options, default_value="b"),
            )
            captured["widget"] = widget
            yield widget

        async def on_mount(self) -> None:
            # Wait until the Select has settled before exiting.
            await self.workers.wait_for_complete()
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()

    widget = captured["widget"]
    assert isinstance(widget, Select)
    assert widget.value == "b"


@pytest.mark.asyncio
async def test_build_select_with_empty_options_falls_back_to_text() -> None:
    from textual.widgets import Input

    from ubo_tui.views.input_widgets import build_widget

    widget = await _run_in_app(
        lambda: build_widget(_Field(type="SELECT", options=_Options(items=[]))),
    )
    assert isinstance(widget, Input)


@pytest.mark.asyncio
async def test_build_color_widget_returns_input() -> None:
    from textual.widgets import Input

    from ubo_tui.views.input_widgets import build_widget

    widget = await _run_in_app(
        lambda: build_widget(_Field(type="COLOR", default_value="#ff00aa")),
    )
    assert isinstance(widget, Input)


@pytest.mark.asyncio
async def test_build_date_and_time_widgets_use_masks() -> None:
    from textual.widgets import MaskedInput

    from ubo_tui.views.input_widgets import build_widget

    date_widget = await _run_in_app(lambda: build_widget(_Field(type="DATE")))
    time_widget = await _run_in_app(lambda: build_widget(_Field(type="TIME")))
    assert isinstance(date_widget, MaskedInput)
    assert isinstance(time_widget, MaskedInput)


@pytest.mark.asyncio
async def test_build_file_widget_returns_file_path_input() -> None:
    from ubo_tui.views.input_widgets import build_widget
    from ubo_tui.widgets.file_path_input import FilePathInput

    widget = await _run_in_app(lambda: build_widget(_Field(type="FILE")))
    assert isinstance(widget, FilePathInput)


@pytest.mark.asyncio
async def test_widget_value_for_switch_returns_string_bool() -> None:
    from textual.widgets import Switch

    from ubo_tui.views.input_widgets import widget_value

    on, off = await _run_in_app(lambda: (Switch(value=True), Switch(value=False)))
    assert widget_value(on) == "True"
    assert widget_value(off) == "False"


@pytest.mark.asyncio
async def test_widget_value_for_input_returns_text() -> None:
    from textual.widgets import Input

    from ubo_tui.views.input_widgets import widget_value

    widget = await _run_in_app(lambda: Input(value="hello"))
    assert widget_value(widget) == "hello"


@pytest.mark.asyncio
async def test_widget_is_valid_required_empty_fails() -> None:
    from textual.widgets import Input

    from ubo_tui.views.input_widgets import widget_is_valid

    widget = await _run_in_app(lambda: Input(value=""))
    field_obj = _Field(type="TEXT", required=True)
    assert widget_is_valid(widget, field_obj) is False


@pytest.mark.asyncio
async def test_widget_is_valid_required_non_empty_passes() -> None:
    from textual.widgets import Input

    from ubo_tui.views.input_widgets import widget_is_valid

    widget = await _run_in_app(lambda: Input(value="something"))
    field_obj = _Field(type="TEXT", required=True)
    assert widget_is_valid(widget, field_obj) is True


@pytest.mark.asyncio
async def test_widget_is_valid_optional_empty_passes() -> None:
    from textual.widgets import Input

    from ubo_tui.views.input_widgets import widget_is_valid

    widget = await _run_in_app(lambda: Input(value=""))
    field_obj = _Field(type="TEXT", required=False)
    assert widget_is_valid(widget, field_obj) is True


@pytest.mark.asyncio
async def test_widget_is_valid_file_required_fails() -> None:
    from ubo_tui.views.input_widgets import widget_is_valid
    from ubo_tui.widgets.file_path_input import FilePathInput

    widget = await _run_in_app(lambda: FilePathInput(value=""))
    field_obj = _Field(type="FILE", required=True)
    assert widget_is_valid(widget, field_obj) is False


@pytest.mark.asyncio
async def test_widget_is_valid_file_with_real_path_passes(tmp_path: Any) -> None:
    from textual.app import App

    from ubo_tui.views.input_widgets import widget_is_valid
    from ubo_tui.widgets.file_path_input import FilePathInput

    real_file = tmp_path / "data.bin"
    real_file.write_bytes(b"hello")

    captured: dict[str, Any] = {}

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            widget = FilePathInput(value=str(real_file))
            captured["widget"] = widget
            yield widget

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()

    assert (
        widget_is_valid(captured["widget"], _Field(type="FILE", required=True))
        is True
    )


@pytest.mark.asyncio
async def test_widget_is_valid_file_with_missing_path_fails(tmp_path: Any) -> None:
    from textual.app import App

    from ubo_tui.views.input_widgets import widget_is_valid
    from ubo_tui.widgets.file_path_input import FilePathInput

    missing = tmp_path / "does-not-exist.bin"

    captured: dict[str, Any] = {}

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            widget = FilePathInput(value=str(missing))
            captured["widget"] = widget
            yield widget

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()

    assert (
        widget_is_valid(captured["widget"], _Field(type="FILE", required=True))
        is False
    )
