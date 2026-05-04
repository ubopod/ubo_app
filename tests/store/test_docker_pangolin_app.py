"""Tests for the Pangolin Docker composition app."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pytest

from ubo_app.store.input.types import InputMethod, InputResult
from ubo_app.utils import secrets

if TYPE_CHECKING:
    from collections.abc import Mapping


DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


class SecretsModule(Protocol):
    """Protocol for the secrets module attributes patched by these tests."""

    SECRETS_PATH: Path


class PangolinModule(Protocol):
    """Protocol for the Pangolin module members used by these tests."""

    COMPOSITIONS_PATH: Path
    secrets: SecretsModule

    async def prepare_pangolin(self) -> bool:
        """Prepare Pangolin composition files."""
        ...


def _import_pangolin() -> PangolinModule:
    """Import the Pangolin module as the Docker service would."""
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)

    try:
        return cast('PangolinModule', import_module('apps.pangolin'))
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


def _use_temp_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pangolin: PangolinModule,
) -> None:
    fake_path = tmp_path / '.secrets.env'
    fake_path.write_text('')
    monkeypatch.setattr(secrets, 'SECRETS_PATH', fake_path)
    monkeypatch.setattr(pangolin.secrets, 'SECRETS_PATH', fake_path)


def _input_result(data: Mapping[str, str]) -> InputResult:
    return InputResult(
        data=data,
        files={},
        method=InputMethod.WEB_DASHBOARD,
    )


@pytest.mark.parametrize(
    ('form_data', 'expected_endpoint'),
    [
        (
            {
                'PANGOLIN_ENDPOINT_MODE': 'https://app.pangolin.net',
                'NEWT_ID': 'site-id',
                'NEWT_SECRET': 'site-secret',
            },
            'https://app.pangolin.net',
        ),
        (
            {
                'PANGOLIN_ENDPOINT_MODE': 'Other',
                'PANGOLIN_ENDPOINT_OTHER': 'https://pangolin.example.com',
                'NEWT_ID': 'site-id',
                'NEWT_SECRET': 'site-secret',
            },
            'https://pangolin.example.com',
        ),
    ],
)
async def test_prepare_pangolin_writes_compose_from_webui_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    form_data: Mapping[str, str],
    expected_endpoint: str,
) -> None:
    """The prepare phase writes a complete Newt compose file."""
    pangolin = _import_pangolin()
    _use_temp_secrets(monkeypatch, tmp_path, pangolin)
    monkeypatch.setattr(pangolin, 'COMPOSITIONS_PATH', tmp_path)

    async def fake_ubo_input(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[str, InputResult]:
        return '', _input_result(form_data)

    monkeypatch.setattr(pangolin, 'ubo_input', fake_ubo_input)

    assert await pangolin.prepare_pangolin()

    compose = (tmp_path / 'pangolin' / 'docker-compose.yml').read_text()
    assert 'image: fosrl/newt' in compose
    assert f'- PANGOLIN_ENDPOINT={expected_endpoint}' in compose
    assert '- NEWT_ID=site-id' in compose
    assert '- NEWT_SECRET=site-secret' in compose
    assert secrets.read_secret('PANGOLIN_ENDPOINT') == expected_endpoint
    assert secrets.read_secret('NEWT_ID') == 'site-id'
    assert secrets.read_secret('NEWT_SECRET') == 'site-secret'


async def test_prepare_pangolin_rejects_missing_custom_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Selecting Other requires a custom endpoint value."""
    pangolin = _import_pangolin()
    _use_temp_secrets(monkeypatch, tmp_path, pangolin)
    monkeypatch.setattr(pangolin, 'COMPOSITIONS_PATH', tmp_path)

    async def fake_ubo_input(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[str, InputResult]:
        return '', _input_result(
            {
                'PANGOLIN_ENDPOINT_MODE': 'Other',
                'NEWT_ID': 'site-id',
                'NEWT_SECRET': 'site-secret',
            },
        )

    monkeypatch.setattr(pangolin, 'ubo_input', fake_ubo_input)

    assert not await pangolin.prepare_pangolin()
    assert not (tmp_path / 'pangolin' / 'docker-compose.yml').exists()


async def test_prepare_pangolin_skips_prompt_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An existing configured Pangolin composition does not prompt again."""
    pangolin = _import_pangolin()
    _use_temp_secrets(monkeypatch, tmp_path, pangolin)
    monkeypatch.setattr(pangolin, 'COMPOSITIONS_PATH', tmp_path)

    composition_path = tmp_path / 'pangolin'
    composition_path.mkdir()
    (composition_path / 'docker-compose.yml').write_text('services: {}\n')
    secrets.write_secret(key='PANGOLIN_ENDPOINT', value='https://app.pangolin.net')
    secrets.write_secret(key='NEWT_ID', value='site-id')
    secrets.write_secret(key='NEWT_SECRET', value='site-secret')

    async def fail_ubo_input(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[str, InputResult]:
        pytest.fail('ubo_input should not be called')

    monkeypatch.setattr(pangolin, 'ubo_input', fail_ubo_input)

    assert await pangolin.prepare_pangolin()
