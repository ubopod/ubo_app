"""Tests for ubo_app.utils.secrets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.utils import secrets

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _use_temp_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    content: str = '',
) -> Path:
    """Point the secrets module at an isolated file for one test."""
    fake_path = tmp_path / '.secrets.env'
    fake_path.write_text(content)
    monkeypatch.setattr(secrets, 'SECRETS_PATH', fake_path)
    return fake_path


class TestListSecrets:
    """Tests for ``secrets.list_secrets``."""

    def test_empty_file_returns_empty_list(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An empty .env file should produce an empty list."""
        _use_temp_secrets(monkeypatch, tmp_path)
        assert secrets.list_secrets() == []

    def test_returns_all_stored_keys(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Every key present in the file should be returned."""
        _use_temp_secrets(
            monkeypatch,
            tmp_path,
            content='OPENAI_API_KEY=sk-test\nFOO=bar\n',
        )
        assert set(secrets.list_secrets()) == {'OPENAI_API_KEY', 'FOO'}

    def test_reflects_writes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Writing a secret should make it show up in list_secrets."""
        _use_temp_secrets(monkeypatch, tmp_path)
        secrets.write_secret(key='openai_api_key', value='sk-new')
        secrets.write_secret(key='anthropic_api_key', value='sk-ant')
        assert set(secrets.list_secrets()) == {
            'openai_api_key',
            'anthropic_api_key',
        }

    def test_reflects_clear(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Clearing a secret should remove it from list_secrets."""
        _use_temp_secrets(
            monkeypatch,
            tmp_path,
            content='KEEP=1\nDROP=2\n',
        )
        secrets.clear_secret('DROP')
        assert set(secrets.list_secrets()) == {'KEEP'}
