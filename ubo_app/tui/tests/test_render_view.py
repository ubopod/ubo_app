"""Tests for the RenderView and its render-kind dispatchers."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest


@dataclass
class _BasicType:
    string: str = ""
    bytes: bytes | None = None
    int64: int = 0
    float: float = 0.0
    bool: bool = False


@dataclass
class _ListProp:
    items: list[_BasicType]


@dataclass
class _PropEntry:
    basic_type: _BasicType | None = None
    list: _ListProp | None = None


@dataclass
class _Props:
    items: dict[str, _PropEntry] = field(default_factory=dict)


@dataclass
class _RenderData:
    title: str = ""
    kind: str = ""
    props: _Props | None = None


def _string_prop(value: str) -> _PropEntry:
    return _PropEntry(basic_type=_BasicType(string=value))


def _string_list_prop(values: list[str]) -> _PropEntry:
    return _PropEntry(
        list=_ListProp(items=[_BasicType(string=v) for v in values]),
    )


@pytest.mark.asyncio
async def test_qr_code_renders_static_with_qr_block_chars() -> None:
    from textual.app import App
    from textual.widgets import Static

    from ubo_tui.views.render import RenderView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            data = _RenderData(
                title="Pair device",
                kind="qr_code",
                props=_Props(items={"value": _string_prop("https://ubo.io/pair")}),
            )
            yield RenderView(data, id="view")

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        statics = list(pilot.app.query(Static))
        rendered = "\n".join(str(static.render()) for static in statics)

    # Must include block-style characters from qrcode's print_ascii.
    assert any(ch in rendered for ch in ("█", "▀", "▄"))


@pytest.mark.asyncio
async def test_qr_code_falls_back_to_url_on_narrow_terminal() -> None:
    from ubo_tui.views.render_kinds.qr import render_qr_text

    output = render_qr_text("https://ubo.io/pair", columns=20)
    assert "ubo.io/pair" in output
    assert "█" not in output


@pytest.mark.asyncio
async def test_text_viewer_renders_text_prop() -> None:
    from textual.app import App
    from textual.widgets import Static

    from ubo_tui.views.render import RenderView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            data = _RenderData(
                kind="text_viewer",
                props=_Props(items={"text": _string_prop("hello world")}),
            )
            yield RenderView(data, id="view")

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        rendered = "\n".join(
            str(static.render()) for static in pilot.app.query(Static)
        )

    assert "hello world" in rendered


@pytest.mark.asyncio
async def test_unsupported_kind_shows_placeholder() -> None:
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.views.render import RenderView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield RenderView(_RenderData(kind="image_viewer"), id="view")

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        rendered = " ".join(
            str(label.render()) for label in pilot.app.query(Label)
        )

    assert "image_viewer" in rendered
    assert "WebUI" in rendered


@pytest.mark.asyncio
async def test_qr_carousel_renders_first_value_with_count_hint() -> None:
    from textual.app import App
    from textual.widgets import Label, Static

    from ubo_tui.views.render import RenderView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            data = _RenderData(
                kind="qr_code_carousel",
                props=_Props(
                    items={
                        "values": _string_list_prop(
                            ["https://a.test", "https://b.test"],
                        ),
                        "labels": _string_list_prop(["Alpha", "Beta"]),
                    },
                ),
            )
            yield RenderView(data, id="view")

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        statics = list(pilot.app.query(Static))
        labels = list(pilot.app.query(Label))
        rendered = "\n".join(str(s.render()) for s in statics)
        label_text = " ".join(str(label.render()) for label in labels)

    assert any(ch in rendered for ch in ("█", "▀", "▄"))
    assert "Alpha" in label_text
    assert "1 of 2" in label_text


@pytest.mark.asyncio
async def test_status_kind_renders_text_prop() -> None:
    from textual.app import App
    from textual.widgets import Label

    from ubo_tui.views.render import RenderView

    class _App(App[None]):
        def compose(self):  # type: ignore[no-untyped-def]
            yield RenderView(
                _RenderData(
                    kind="status",
                    props=_Props(items={"text": _string_prop("Working...")}),
                ),
                id="view",
            )

        async def on_mount(self) -> None:
            self.exit()

    async with _App().run_test() as pilot:
        await pilot.pause()
        labels = list(pilot.app.query(Label))
        rendered = " ".join(str(label.render()) for label in labels)

    assert "Working..." in rendered
