"""End-to-end tests for the InputForm modal screen using Textual Pilot."""

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


@dataclass
class _Fields:
    items: list[_Field]


@dataclass
class _Description:
    id: str = "demand-1"
    title: str | None = "Login"
    prompt: str | None = "Please log in"
    fields: Any = None


class _FakeClient:
    """Captures the args passed to provide_input / cancel_input."""

    def __init__(self) -> None:
        self.provided: list[tuple[str, str, dict[str, str]]] = []
        self.cancelled: list[str] = []
        self.upload_starts: list[dict[str, Any]] = []
        self.upload_chunks: list[dict[str, Any]] = []
        self.upload_completes: list[dict[str, Any]] = []

    def provide_input(
        self,
        input_id: str,
        value: str,
        data: dict[str, str],
        files: dict[str, bytes] | None = None,  # noqa: ARG002
    ) -> None:
        self.provided.append((input_id, value, dict(data)))

    def cancel_input(self, input_id: str) -> None:
        self.cancelled.append(input_id)

    def upload_file_start(self, **kwargs: Any) -> None:
        self.upload_starts.append(kwargs)

    def upload_file_chunk(self, **kwargs: Any) -> None:
        self.upload_chunks.append(kwargs)

    def upload_file_complete(self, **kwargs: Any) -> None:
        self.upload_completes.append(kwargs)


class _Harness:
    """Minimal Textual app that pushes the InputForm on mount."""

    def __init__(self, description: _Description, client: _FakeClient) -> None:
        self.description = description
        self.client = client


def _make_app(description: _Description, client: _FakeClient) -> Any:
    from textual.app import App

    from ubo_tui.views.input_form import InputForm

    class _App(App[None]):
        async def on_mount(self) -> None:
            await self.push_screen(InputForm(description, client))

    return _App()


@pytest.mark.asyncio
async def test_submit_dispatches_provide_input_with_field_values() -> None:
    description = _Description(
        id="demand-1",
        title="Login",
        prompt="Enter credentials",
        fields=_Fields(
            items=[
                _Field(
                    name="username",
                    label="Username",
                    type="TEXT",
                    required=True,
                ),
                _Field(name="password", label="Password", type="PASSWORD"),
            ],
        ),
    )
    client = _FakeClient()

    app = _make_app(description, client)
    async with app.run_test() as pilot:
        # First field auto-focused; type the username
        await pilot.press(*"alice")
        await pilot.press("tab")  # move to password
        await pilot.press(*"hunter2")
        await pilot.press("ctrl+s")  # submit
        await pilot.pause()

    assert client.provided == [
        ("demand-1", "alice", {"username": "alice", "password": "hunter2"}),
    ]
    assert client.cancelled == []


@pytest.mark.asyncio
async def test_escape_dispatches_cancel_input() -> None:
    description = _Description(
        id="demand-2",
        fields=_Fields(items=[_Field(name="value", type="TEXT")]),
    )
    client = _FakeClient()

    app = _make_app(description, client)
    async with app.run_test() as pilot:
        await pilot.press("escape")
        await pilot.pause()

    assert client.cancelled == ["demand-2"]
    assert client.provided == []


@pytest.mark.asyncio
async def test_required_empty_field_blocks_submit() -> None:
    description = _Description(
        id="demand-3",
        fields=_Fields(
            items=[_Field(name="username", type="TEXT", required=True)],
        ),
    )
    client = _FakeClient()

    app = _make_app(description, client)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert client.provided == []
    assert client.cancelled == []


@pytest.mark.asyncio
async def test_no_fields_renders_single_value_input() -> None:
    description = _Description(id="demand-4", fields=None)
    client = _FakeClient()

    app = _make_app(description, client)
    async with app.run_test() as pilot:
        await pilot.press(*"hello")
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert client.provided == [("demand-4", "hello", {"value": "hello"})]


@pytest.mark.asyncio
async def test_submit_with_file_field_emits_upload_id_and_runs_upload(
    tmp_path: Any,
) -> None:
    """FILE fields should populate ``<name>_upload_id`` / ``<name>_name`` and
    trigger a chunked upload after InputProvideAction is dispatched."""
    real_file = tmp_path / "payload.bin"
    real_file.write_bytes(b"hello world")

    description = _Description(
        id="demand-file",
        fields=_Fields(
            items=[
                _Field(name="username", label="Username", type="TEXT"),
                _Field(
                    name="attachment",
                    label="Attachment",
                    type="FILE",
                    default_value=str(real_file),
                ),
            ],
        ),
    )
    client = _FakeClient()

    app = _make_app(description, client)
    async with app.run_test() as pilot:
        await pilot.press(*"alice")  # username (auto-focused)
        await pilot.press("ctrl+s")
        # The upload runs in a background task; wait for it to settle.
        await pilot.pause()
        for _ in range(20):
            if client.upload_completes:
                break
            await pilot.pause()

    assert len(client.provided) == 1
    _, primary_value, data = client.provided[0]
    # Primary value comes from the first non-FILE field.
    assert primary_value == "alice"
    assert data["username"] == "alice"
    assert data["attachment_name"] == "payload.bin"
    assert "attachment_upload_id" in data
    upload_id = data["attachment_upload_id"]

    # The chunked upload should have run with the same upload_id.
    assert client.upload_starts
    assert client.upload_starts[0]["upload_id"] == upload_id
    assert client.upload_chunks
    assert client.upload_chunks[0]["data"] == b"hello world"
    assert client.upload_completes == [{"upload_id": upload_id}]


@pytest.mark.asyncio
async def test_submit_with_invalid_file_path_blocks_submit(tmp_path: Any) -> None:
    """A required FILE field pointing at a missing path should block submit."""
    description = _Description(
        id="demand-file-bad",
        fields=_Fields(
            items=[
                _Field(
                    name="attachment",
                    label="Attachment",
                    type="FILE",
                    required=True,
                    default_value=str(tmp_path / "missing.bin"),
                ),
            ],
        ),
    )
    client = _FakeClient()

    app = _make_app(description, client)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert client.provided == []
    assert client.upload_starts == []
