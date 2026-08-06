"""The custom wake-word upload form, for both pool-backed engines.

OpenWakeWord takes a single ``.onnx``; microWakeWord takes a pair — the
``.tflite`` weights plus the ``.json`` manifest carrying its detection
parameters. The two share one form-running path, so these tests pin the parts
that must stay engine-specific: the field list, which model pool a duplicate
stem is checked against, and the OpenWakeWord-only shared-helpers gate.

They also cover the fact that ``required=True`` is not enforced end to end: an
untouched file input still arrives as a *successful* zero-byte upload on the
gRPC path, so an omitted half has to be caught before anything waits on it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from ubo_app.store.input.types import InputFieldType
from ubo_app.store.services.speech_recognition import (
    WakeWordEngineName,
    WakeWordModelStatus,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from types import ModuleType

SERVICE_DIR = (
    Path(__file__).resolve().parents[2]
    / 'ubo_app'
    / 'services'
    / '090-speech-recognition'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

MICRO = WakeWordEngineName.MICROWAKEWORD
OWW = WakeWordEngineName.OPENWAKEWORD


class _Result:
    """Stand-in for the ``InputResult`` ``ubo_input`` hands back."""

    def __init__(self, data: Mapping[str, str]) -> None:
        self.data = data


@pytest.fixture
def menu() -> Iterator[ModuleType]:
    """Import ``wake_menu`` with its store dispatch captured."""
    import wake_menu  # type: ignore[reportMissingImports]

    original = wake_menu.store.dispatch
    wake_menu.store.dispatch = lambda *actions, **_kwargs: _DISPATCHED.extend(actions)
    _DISPATCHED.clear()
    try:
        yield wake_menu
    finally:
        wake_menu.store.dispatch = original


_DISPATCHED: list[object] = []


def _arrange(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    data: Mapping[str, str],
    *,
    micro_models: list[str] | None = None,
    oww_models: list[str] | None = None,
    helpers: bool = True,
) -> dict[str, list[Any]]:
    """Stub the form, the pools and the installers; return their call logs."""
    calls: dict[str, list[Any]] = {'prompt': [], 'upload': [], 'install': []}

    async def _ubo_input(*, prompt: str, descriptions: list[Any]) -> tuple[None, Any]:
        calls['prompt'].append((prompt, descriptions[0].fields))
        return (None, _Result(data))

    async def _await_completed_upload(upload_id: str) -> bytes:
        calls['upload'].append(upload_id)
        return b'payload'

    def _install(model_id: str, *, manifest: bytes, weights: bytes) -> bool:
        calls['install'].append((model_id, manifest, weights))
        return True

    monkeypatch.setattr(menu, 'ubo_input', _ubo_input)
    monkeypatch.setattr(menu, 'micro_scan_models', lambda: micro_models or [])
    monkeypatch.setattr(menu, 'scan_models', lambda: oww_models or [])
    monkeypatch.setattr(menu, 'micro_install_uploaded_model', _install)
    monkeypatch.setattr(menu, 'helpers_available', lambda: helpers)
    monkeypatch.setattr(
        'ubo_app.utils.file_upload.await_completed_upload',
        _await_completed_upload,
    )
    return calls


def _micro_form_data(**overrides: str) -> dict[str, str]:
    """Build a complete two-file microWakeWord submission."""
    return {
        'label': 'My Word',
        'weights_file_upload_id': 'weights-id',
        'weights_file_name': 'my_word.tflite',
        'manifest_file_upload_id': 'manifest-id',
        'manifest_file_name': 'my_word.json',
        **overrides,
    }


def test_the_microwakeword_form_offers_two_pickers(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pair needs a picker each — one file can't describe a microWakeWord model."""
    calls = _arrange(menu, monkeypatch, _micro_form_data())

    asyncio.run(menu._upload_model_form(MICRO))  # noqa: SLF001

    _prompt, fields = calls['prompt'][0]
    assert [(field.name, field.type) for field in fields] == [
        ('label', InputFieldType.TEXT),
        ('weights_file', InputFieldType.FILE),
        ('manifest_file', InputFieldType.FILE),
    ]


def test_each_engine_links_to_its_own_training_site(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The upload form says where a phrase the catalog lacks can be trained."""
    calls = _arrange(menu, monkeypatch, _micro_form_data())
    asyncio.run(menu._upload_model_form(MICRO))  # noqa: SLF001
    _prompt, micro_fields = calls['prompt'][0]

    calls = _arrange(
        menu,
        monkeypatch,
        {
            'label': 'My Word',
            'model_file_upload_id': 'model-id',
            'model_file_name': 'my_word.onnx',
        },
    )
    asyncio.run(menu._upload_model_form(OWW))  # noqa: SLF001
    _prompt, oww_fields = calls['prompt'][0]

    assert 'https://microwakeword.com/' in micro_fields[1].description
    assert 'https://openwakeword.com/' in oww_fields[1].description


def test_a_blank_second_picker_is_rejected_without_awaiting_an_upload(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An untouched file input arrives as a successful zero-byte upload.

    It must be caught from the empty filename before anything blocks on the
    120 s upload backstop.
    """
    calls = _arrange(
        menu,
        monkeypatch,
        _micro_form_data(manifest_file_name=''),
    )

    async def _empty(upload_id: str) -> bytes:
        calls['upload'].append(upload_id)
        return b''

    monkeypatch.setattr('ubo_app.utils.file_upload.await_completed_upload', _empty)

    asyncio.run(menu._upload_model_form(MICRO))  # noqa: SLF001

    assert calls['upload'] == []
    assert calls['install'] == []


def test_an_absent_second_picker_is_rejected(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Flask fallback omits the upload id entirely for an empty field."""
    data = _micro_form_data()
    del data['manifest_file_upload_id']
    calls = _arrange(menu, monkeypatch, data)

    asyncio.run(menu._upload_model_form(MICRO))  # noqa: SLF001

    assert calls['install'] == []


def test_a_failed_upload_installs_nothing(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A half that never arrives is reported, not raised past the handler."""
    calls = _arrange(menu, monkeypatch, _micro_form_data())

    async def _fail(upload_id: str) -> bytes:
        if upload_id == 'manifest-id':
            message = 'upload timed out'
            raise RuntimeError(message)
        return b'payload'

    monkeypatch.setattr('ubo_app.utils.file_upload.await_completed_upload', _fail)

    asyncio.run(menu._upload_model_form(MICRO))  # noqa: SLF001

    assert calls['install'] == []


def test_a_duplicate_stem_is_rejected_against_the_microwakeword_pool(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overwriting wouldn't reload the engine, so the user must delete first."""
    calls = _arrange(menu, monkeypatch, _micro_form_data(), micro_models=['my_word'])

    asyncio.run(menu._upload_model_form(MICRO))  # noqa: SLF001

    assert calls['install'] == []


def test_an_openwakeword_stem_does_not_block_a_microwakeword_upload(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pools are separate; the duplicate check must follow the engine."""
    calls = _arrange(menu, monkeypatch, _micro_form_data(), oww_models=['my_word'])

    asyncio.run(menu._upload_model_form(MICRO))  # noqa: SLF001

    assert [call[0] for call in calls['install']] == ['my_word']


def test_the_microwakeword_upload_ignores_the_openwakeword_helper_gate(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every microWakeWord model is self-contained — there are no shared helpers."""
    calls = _arrange(menu, monkeypatch, _micro_form_data(), helpers=False)

    asyncio.run(menu._upload_model_form(MICRO))  # noqa: SLF001

    assert [call[0] for call in calls['install']] == ['my_word']


def test_a_successful_upload_reports_the_pool_and_marks_models_available(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the status action a first-ever upload leaves the engine unavailable."""
    _arrange(menu, monkeypatch, _micro_form_data(), micro_models=[])

    asyncio.run(menu._upload_model_form(MICRO))  # noqa: SLF001

    statuses = [
        action
        for action in _DISPATCHED
        if getattr(action, 'status', None) is WakeWordModelStatus.AVAILABLE
    ]
    assert len(statuses) == 1
    assert getattr(statuses[0], 'engine_name', None) is MICRO


def test_an_engine_without_a_model_pool_opens_no_form(
    menu: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vosk matches spoken phrases; a remote dispatch must not open the form."""
    calls = _arrange(menu, monkeypatch, _micro_form_data())

    asyncio.run(menu._upload_model_form(WakeWordEngineName.VOSK))  # noqa: SLF001

    assert calls['prompt'] == []
