"""Tests for assistant subprocess logging environment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


def _load_ubo_handle(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'assistant_service_ubo_handle',
        SERVICE_PATH / 'ubo_handle.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.register = lambda **_: None  # type: ignore[attr-defined]
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_assistant_subprocess_log_env_defaults_to_main_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Assistant subprocess writes logs beside the main process log by default."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('UBO_ASSISTANT_LOG_PATH', raising=False)
    monkeypatch.delenv('UBO_ASSISTANT_LOG_LEVEL', raising=False)
    ubo_handle = _load_ubo_handle(monkeypatch)

    env = cast('dict[str, str]', ubo_handle.binary_env_provider())

    assert env['UBO_ASSISTANT_LOG_PATH'] == str(tmp_path / 'ubo-assistant.log')
    assert env['UBO_ASSISTANT_LOG_LEVEL'] == 'INFO'


def test_assistant_subprocess_log_env_respects_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Explicit assistant log env values pass through to the subprocess."""
    log_path = tmp_path / 'custom-assistant.log'
    monkeypatch.setenv('UBO_ASSISTANT_LOG_PATH', str(log_path))
    monkeypatch.setenv('UBO_ASSISTANT_LOG_LEVEL', 'DEBUG')
    ubo_handle = _load_ubo_handle(monkeypatch)

    env = cast('dict[str, str]', ubo_handle.binary_env_provider())

    assert env['UBO_ASSISTANT_LOG_PATH'] == str(log_path)
    assert env['UBO_ASSISTANT_LOG_LEVEL'] == 'DEBUG'


def test_assistant_subprocess_whisker_env_respects_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Explicit Whisker debug env values pass through to the subprocess."""
    whisker_file = tmp_path / 'whisker.bin'
    monkeypatch.setenv('UBO_ASSISTANT_WHISKER_ENABLED', 'true')
    monkeypatch.setenv('UBO_ASSISTANT_WHISKER_FILE', str(whisker_file))
    ubo_handle = _load_ubo_handle(monkeypatch)

    env = cast('dict[str, str]', ubo_handle.binary_env_provider())

    assert env['UBO_ASSISTANT_WHISKER_ENABLED'] == 'true'
    assert env['UBO_ASSISTANT_WHISKER_FILE'] == str(whisker_file)
