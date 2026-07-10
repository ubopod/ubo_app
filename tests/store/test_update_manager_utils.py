"""Fast, isolated tests for update checking, installation, and About menus."""

from __future__ import annotations

import importlib
import inspect
import sys
import tarfile
import weakref
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
import requests

from ubo_app.store.update_manager.types import (
    UpdateManagerState,
    UpdateManagerUpdateEvent,
    UpdateStatus,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path
    from typing import Self


class _RecordingStore:
    """Store double supporting decorators, state callbacks, and dispatches."""

    def __init__(self, state: object | None = None) -> None:
        self.state = state
        self.actions: list[object] = []

    def with_state(
        self,
        _selector: Callable[..., object],
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        """Return a transparent decorator for import-time registration."""
        return lambda callback: callback

    def autorun(
        self,
        _selector: Callable[..., object],
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        """Return a transparent decorator for import-time registration."""
        return lambda callback: callback

    def dispatch(
        self,
        *actions: object,
        with_state: Callable[[object | None], object] | None = None,
    ) -> None:
        """Record direct actions or resolve a state-dependent action."""
        self.actions.extend(actions)
        if with_state is not None:
            self.actions.append(with_state(self.state))


_STORE_MAIN_MODULE = 'ubo_app.store.main'
_UPDATE_MODULE = 'ubo_app.store.update_manager.utils'
_previous_store_main = sys.modules.get(_STORE_MAIN_MODULE)
_previous_update_module = sys.modules.get(_UPDATE_MODULE)
_import_store = _RecordingStore()
_fake_store_main = ModuleType(_STORE_MAIN_MODULE)
_fake_store_main.store = _import_store  # type: ignore[attr-defined]
sys.modules[_STORE_MAIN_MODULE] = _fake_store_main
update_module: ModuleType | None = None
try:
    update_module = importlib.import_module(_UPDATE_MODULE)
finally:
    if _previous_store_main is None:
        del sys.modules[_STORE_MAIN_MODULE]
    else:
        sys.modules[_STORE_MAIN_MODULE] = _previous_store_main
    if _previous_update_module is None:
        del sys.modules[_UPDATE_MODULE]
        update_package = sys.modules['ubo_app.store.update_manager']
        if (
            update_module is not None
            and getattr(update_package, 'utils', None) is update_module
        ):
            delattr(update_package, 'utils')
assert update_module is not None
loaded_update_module = update_module


class _Response:
    """Async HTTP response double."""

    def __init__(
        self,
        data: dict[str, object],
        status: int = requests.codes.ok,
    ) -> None:
        self.data = data
        self.status = status

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self) -> dict[str, object]:
        return self.data

    def raise_for_status(self) -> None:
        if self.status != requests.codes.ok:
            msg = f'HTTP {self.status}'
            raise RuntimeError(msg)


class _Session:
    """Async client-session double returning one response."""

    def __init__(self, response: _Response) -> None:
        self.response = response

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def get(self, *_args: object, **_kwargs: object) -> _Response:
        return self.response


def _patch_http(monkeypatch: pytest.MonkeyPatch, response: _Response) -> None:
    """Route update-manager HTTP calls to a deterministic response."""
    monkeypatch.setattr(
        loaded_update_module.aiohttp,
        'ClientSession',
        lambda: _Session(response),
    )


def _autorun_callback(value: object) -> Callable[..., object]:
    """Return the raw reaction from either a real Autorun or the import double."""
    wrapped = cast('SimpleNamespace', value)
    if not hasattr(wrapped, '_func'):
        return cast('Callable[..., object]', value)
    callback = wrapped._func  # noqa: SLF001
    if isinstance(callback, weakref.ReferenceType):
        callback = callback()
    assert callback is not None
    return cast('Callable[..., object]', callback)


async def test_check_version_filters_stable_and_beta_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stable checks exclude dev/yanked releases while beta checks retain devs."""
    data = {
        'info': {'version': '2.0.0'},
        'releases': {
            '2.0.0': [{'yanked': False, 'upload_time': '2026-03-03'}],
            '2.1.0.dev1': [{'yanked': False, 'upload_time': '2026-03-04'}],
            '1.9.0': [{'yanked': False, 'upload_time': '2026-03-02'}],
            '1.8.0': [{'yanked': True, 'upload_time': '2026-03-01'}],
        },
    }
    store = _RecordingStore(state=None)
    monkeypatch.setattr(loaded_update_module, 'store', store)
    _patch_http(monkeypatch, _Response(data))
    check_version = inspect.unwrap(loaded_update_module.check_version)

    await check_version(beta_versions=False)
    stable = cast('SimpleNamespace', store.actions[-1])
    await check_version(beta_versions=True)
    beta = cast('SimpleNamespace', store.actions[-1])

    assert stable.latest_version == '2.0.0'
    assert stable.recent_versions == ['2.0.0', '1.9.0']
    assert stable.flash_notification is True
    assert beta.latest_version == '2.1.0.dev1'
    assert beta.recent_versions == ['2.1.0.dev1', '2.0.0', '1.9.0']


async def test_check_version_reports_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected HTTP failures become a failed-check store action."""
    store = _RecordingStore()
    monkeypatch.setattr(loaded_update_module, 'store', store)

    class _FailingSession:
        async def __aenter__(self) -> Self:
            msg = 'offline'
            raise OSError(msg)

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        loaded_update_module.aiohttp,
        'ClientSession',
        _FailingSession,
    )

    await inspect.unwrap(loaded_update_module.check_version)(beta_versions=False)

    assert [type(action).__name__ for action in store.actions] == [
        'UpdateManagerReportFailedCheckAction',
    ]


async def test_get_sdist_url_returns_archive_and_rejects_missing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PyPI metadata must include an sdist URL for installation."""
    _patch_http(
        monkeypatch,
        _Response({'urls': [{'packagetype': 'sdist', 'url': 'https://example/s.tgz'}]}),
    )
    assert await loaded_update_module._get_pypi_sdist_url('2.0.0') == (  # noqa: SLF001
        'https://example/s.tgz'
    )

    _patch_http(monkeypatch, _Response({'urls': [{'packagetype': 'wheel'}]}))
    with pytest.raises(RuntimeError, match='No sdist found'):
        await loaded_update_module._get_pypi_sdist_url('2.0.0')  # noqa: SLF001


async def test_update_runs_local_archive_and_progress_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The update pipeline extracts install.sh and reports command progress."""
    assets_path = tmp_path / 'assets'
    installation_path = tmp_path / 'installation'
    installation_path.mkdir()
    (installation_path / '.packages-count').write_text('2', encoding='utf-8')
    source_script = tmp_path / 'source-install.sh'
    source_script.write_text('#!/bin/sh\n', encoding='utf-8')
    store = _RecordingStore()
    monkeypatch.setattr(loaded_update_module, 'store', store)
    monkeypatch.setattr(loaded_update_module, 'UPDATE_ASSETS_PATH', assets_path)
    monkeypatch.setattr(loaded_update_module, 'INSTALLATION_PATH', installation_path)

    async def _sdist_url(_version: str | None) -> str:
        return 'https://example/package.tar.gz'

    async def _download_file(*, url: str, path: Path) -> AsyncIterator[tuple[int, int]]:
        assert url.endswith('package.tar.gz')
        with tarfile.open(path, 'w:gz') as archive:
            archive.add(
                source_script,
                arcname='pkg/ubo_app/system/scripts/install.sh',
            )
        yield 1, 2

    async def _send_command(
        *_args: str,
        **_kwargs: object,
    ) -> AsyncIterator[str]:
        async def _lines() -> AsyncIterator[str]:
            yield 'Installing dependencies...'
            yield 'Collecting demo-package'
            yield 'Bootstrapping completed'

        return _lines()

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(loaded_update_module, '_get_pypi_sdist_url', _sdist_url)
    monkeypatch.setattr(loaded_update_module, 'download_file', _download_file)
    monkeypatch.setattr(loaded_update_module, 'send_command', _send_command)
    monkeypatch.setattr(loaded_update_module.asyncio, 'sleep', _no_sleep)

    await loaded_update_module._update('2.0.0')  # noqa: SLF001

    extracted = assets_path / 'install.sh'
    assert extracted.read_text(encoding='utf-8') == '#!/bin/sh\n'
    notifications = [
        cast('SimpleNamespace', action).notification for action in store.actions
    ]
    assert notifications[0].title == 'Update in progress'
    assert any(
        notification.content == 'Installing system dependencies...'
        for notification in notifications
    )
    assert any(
        notification.content == 'Downloading demo-package'
        for notification in notifications
    )
    assert notifications[-1].title == 'Update Complete'


async def test_update_ignores_none_and_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing versions are ignored and failed installs produce recovery actions."""
    store = _RecordingStore()
    calls: list[str | None] = []

    async def _failing_update(version: str | None) -> None:
        calls.append(version)
        msg = 'install failed'
        raise RuntimeError(msg)

    monkeypatch.setattr(loaded_update_module, 'store', store)
    monkeypatch.setattr(loaded_update_module, '_update', _failing_update)

    await loaded_update_module.update(UpdateManagerUpdateEvent(version=None))
    await loaded_update_module.update(UpdateManagerUpdateEvent(version='2.0.0'))

    assert calls == ['2.0.0']
    assert [type(action).__name__ for action in store.actions] == [
        'NotificationsAddAction',
        'UpdateManagerRequestCheckAction',
    ]
    assert cast('SimpleNamespace', store.actions[0]).notification.title == (
        'Failed to update'
    )


def test_activate_version_repoints_environment_and_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Activating an installed version atomically repoints the env symlink."""
    store = _RecordingStore()
    version = tmp_path / '2.0.0'
    version.mkdir()
    env_path = tmp_path / 'env'
    env_path.write_text('old', encoding='utf-8')
    monkeypatch.setattr(loaded_update_module, 'store', store)
    monkeypatch.setattr(loaded_update_module, 'INSTALLATION_PATH', tmp_path)

    loaded_update_module.activate_version(tmp_path / 'missing')
    loaded_update_module.activate_version(version)

    assert env_path.is_symlink()
    assert env_path.resolve() == version.resolve()
    assert [type(action).__name__ for action in store.actions] == ['FinishAction']


@pytest.mark.parametrize(
    ('status', 'beta_versions', 'expected_keys'),
    [
        pytest.param(UpdateStatus.CHECKING, False, ['checking'], id='checking'),
        pytest.param(
            UpdateStatus.FAILED_TO_CHECK,
            False,
            ['failed_to_check'],
            id='failed',
        ),
        pytest.param(
            UpdateStatus.UP_TO_DATE,
            False,
            ['up_to_date', 'recent_versions'],
            id='current-stable',
        ),
        pytest.param(
            UpdateStatus.UP_TO_DATE,
            True,
            ['up_to_date', 'recent_versions', 'installed_versions'],
            id='current-beta',
        ),
        pytest.param(
            UpdateStatus.OUTDATED,
            True,
            ['update_latest', 'recent_versions', 'installed_versions'],
            id='outdated-beta',
        ),
        pytest.param(UpdateStatus.UPDATING, False, ['updating'], id='updating'),
    ],
)
def test_about_menu_covers_every_update_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: UpdateStatus,
    beta_versions: bool,  # noqa: FBT001
    expected_keys: list[str],
) -> None:
    """Every update status produces its intended About-menu actions."""
    store = _RecordingStore()
    handlers: dict[str, Callable[..., object]] = {}
    installed = tmp_path / '1.0.0'
    installed.mkdir()

    def _register(
        action_id: str,
        handler: Callable[..., object],
        **_kwargs: object,
    ) -> Callable[..., object]:
        handlers[action_id] = handler
        return handler

    monkeypatch.setattr(loaded_update_module, 'store', store)
    monkeypatch.setattr(loaded_update_module, 'register_action', _register)
    monkeypatch.setattr(
        loaded_update_module,
        'unregister_action',
        lambda action_id: handlers.pop(action_id, None),
    )
    monkeypatch.setattr(
        loaded_update_module,
        'get_installed_versions',
        lambda: [installed],
    )
    loaded_update_module._about_action_ids.clear()  # noqa: SLF001
    state = UpdateManagerState(
        current_version='1.0.0',
        latest_version='2.0.0',
        recent_versions=['2.0.0', '1.0.0'],
        update_status=status,
    )

    _autorun_callback(loaded_update_module.about_menu_items)((state, beta_versions))

    main_menu = cast('SimpleNamespace', store.actions[-1])
    assert main_menu.menu_id == 'about:main'
    assert [item.key for item in main_menu.items] == expected_keys
    loaded_update_module._about_action_ids.clear()  # noqa: SLF001


@pytest.mark.parametrize(
    ('path', 'expected'),
    [
        (('main', 'about:main'), 'about:main'),
        (('main', 'about:main', 'update:recent-versions'), 'update:recent-versions'),
        (('main', 'settings'), None),
        (('main', 'about:main', 'too', 'deep'), None),
    ],
)
def test_about_path_matcher(path: tuple[str, ...], expected: str | None) -> None:
    """Only the About root and one nested submenu resolve to dynamic menus."""
    assert loaded_update_module._about_path_matcher(path) == expected  # noqa: SLF001
