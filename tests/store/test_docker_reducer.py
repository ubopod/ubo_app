"""Reducer tests for the Docker service and per-image lifecycle reducers.

Uses the same file-path loader discipline as ``test_docker_lan_toggle.py``:
every identity-sensitive symbol is read back off the freshly-imported reducer
module so the reducer's ``match`` / ``isinstance`` checks and the test's
constructed actions share one module generation.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

DOCKER_SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app' / 'services' / '080-docker'


def _reducer_module() -> ModuleType:
    docker_path = str(DOCKER_SERVICE_PATH)
    if docker_path not in sys.path:
        sys.path.insert(0, docker_path)
    try:
        return import_module('reducer')
    finally:
        if docker_path in sys.path:
            sys.path.remove(docker_path)


@pytest.fixture(autouse=True)
def _isolated_persistent_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep DockerServiceState's persistent-store reads off the real file."""
    store_path = tmp_path / 'state.json'
    monkeypatch.setattr('ubo_app.constants.PERSISTENT_STORE_PATH', store_path)
    monkeypatch.setattr(
        'ubo_app.utils.persistent_store.PERSISTENT_STORE_PATH',
        store_path,
    )


def _image_state(module: ModuleType, **kwargs: object) -> object:
    defaults: dict[str, object] = {
        'id': 'test-image',
        'label': 'Test',
        'instructions': None,
    }
    defaults.update(kwargs)
    return module.ImageState(**defaults)


# --- service_reducer -----------------------------------------------------


def test_service_init_builds_state_and_non_init_raises() -> None:
    """InitAction builds the service state; anything else against None raises."""
    module = _reducer_module()
    assert isinstance(
        module.service_reducer(None, module.InitAction()),
        module.DockerServiceState,
    )
    with pytest.raises(module.InitializationActionError):
        module.service_reducer(None, module.DockerStartAction())


def test_service_set_status() -> None:
    """DockerSetStatusAction replaces the service status."""
    module = _reducer_module()
    state = module.service_reducer(None, module.InitAction())

    result = module.service_reducer(
        state,
        module.DockerSetStatusAction(status=module.DockerStatus.RUNNING),
    )

    assert result.status == module.DockerStatus.RUNNING


def test_service_store_and_remove_username() -> None:
    """Usernames are stored per-registry and removable."""
    module = _reducer_module()
    state = module.service_reducer(None, module.InitAction())

    state = module.service_reducer(
        state,
        module.DockerStoreUsernameAction(registry='ghcr.io', username='me'),
    )
    assert state.usernames == {'ghcr.io': 'me'}

    state = module.service_reducer(
        state,
        module.DockerRemoveUsernameAction(registry='ghcr.io'),
    )
    assert state.usernames == {}


@pytest.mark.parametrize(
    ('action_name', 'status_name', 'event_name'),
    [
        ('DockerInstallAction', 'INSTALLING', 'DockerInstallEvent'),
        ('DockerStartAction', 'UNKNOWN', 'DockerStartEvent'),
        ('DockerStopAction', 'UNKNOWN', 'DockerStopEvent'),
    ],
)
def test_service_lifecycle_actions_emit_events(
    action_name: str,
    status_name: str,
    event_name: str,
) -> None:
    """Install/Start/Stop set the expected status and emit their event."""
    module = _reducer_module()
    state = module.service_reducer(None, module.InitAction())

    result = module.service_reducer(state, getattr(module, action_name)())

    assert result.state.status == getattr(module.DockerStatus, status_name)
    assert any(
        isinstance(event, getattr(module, event_name))
        for event in (result.events or [])
    )


def test_service_unhandled_action_returns_state_unchanged() -> None:
    """An action matching no service case leaves the state untouched."""
    module = _reducer_module()
    state = module.service_reducer(None, module.InitAction())

    assert module.service_reducer(state, module.InitAction()) is state


# --- image_reducer -------------------------------------------------------


def test_image_init_without_label_raises() -> None:
    """A plain init (no label payload) is an initialization error."""
    module = _reducer_module()
    with pytest.raises(module.InitializationActionError):
        module.image_reducer(None, module.InitAction())


def test_action_for_a_different_image_is_ignored() -> None:
    """An image action addressed to another image passes through unchanged."""
    module = _reducer_module()
    state = _image_state(module)

    result = module.image_reducer(
        state,
        module.DockerImageSetDockerIdAction(image='other', docker_id='abc'),
    )

    assert result is state


def test_set_status_updates_status_ports_and_ip() -> None:
    """Set-status records the new status, ports, and container ip."""
    module = _reducer_module()
    state = _image_state(module)

    result = module.image_reducer(
        state,
        module.DockerImageSetStatusAction(
            image='test-image',
            status=module.DockerItemStatus.RUNNING,
            ports=['8080/tcp'],
            ip='10.0.0.5',
        ),
    )

    assert result.status == module.DockerItemStatus.RUNNING
    assert result.ports == ['8080/tcp']
    assert result.container_ip == '10.0.0.5'


def test_starting_while_running_stays_running() -> None:
    """A late STARTING report never regresses an already-RUNNING image."""
    module = _reducer_module()
    state = _image_state(module, status=module.DockerItemStatus.RUNNING)

    result = module.image_reducer(
        state,
        module.DockerImageSetStatusAction(
            image='test-image',
            status=module.DockerItemStatus.STARTING,
        ),
    )

    assert result.status == module.DockerItemStatus.RUNNING


def test_set_docker_id_and_update_metadata() -> None:
    """Docker id and instruction metadata are recorded on the image."""
    module = _reducer_module()
    state = _image_state(module)

    state = module.image_reducer(
        state,
        module.DockerImageSetDockerIdAction(image='test-image', docker_id='deadbeef'),
    )
    assert state.docker_id == 'deadbeef'

    state = module.image_reducer(
        state,
        module.DockerImageUpdateMetadataAction(
            image='test-image',
            instructions='scan the QR',
        ),
    )
    assert state.instructions == 'scan the QR'


@pytest.mark.parametrize(
    ('action_name', 'is_composition', 'event_name'),
    [
        ('DockerImageFetchAction', True, 'DockerImageFetchCompositionEvent'),
        ('DockerImageFetchAction', False, 'DockerImageFetchEvent'),
        ('DockerImageRemoveAction', True, 'DockerImageRemoveCompositionEvent'),
        ('DockerImageRemoveAction', False, 'DockerImageRemoveEvent'),
        ('DockerImageRunAction', True, 'DockerImageRunCompositionEvent'),
        ('DockerImageRunAction', False, 'DockerImageRunContainerEvent'),
        ('DockerImageStopAction', True, 'DockerImageStopCompositionEvent'),
        ('DockerImageStopAction', False, 'DockerImageStopContainerEvent'),
    ],
)
def test_lifecycle_routes_composition_vs_container(
    monkeypatch: pytest.MonkeyPatch,
    action_name: str,
    is_composition: bool,  # noqa: FBT001
    event_name: str,
) -> None:
    """Fetch/Remove/Run/Stop pick composition vs container events by image type."""
    module = _reducer_module()
    monkeypatch.setattr(
        module,
        'IMAGES',
        {'test-image': SimpleNamespace(is_composition=is_composition)},
    )
    state = _image_state(module)

    result = module.image_reducer(
        state,
        getattr(module, action_name)(image='test-image'),
    )

    event_cls = getattr(module, event_name)
    assert any(
        isinstance(event, event_cls) and event.image == 'test-image'
        for event in (result.events or [])
    )


@pytest.mark.parametrize(
    ('action_name', 'event_name'),
    [
        ('DockerImageReleaseAction', 'DockerImageReleaseCompositionEvent'),
        ('DockerImageRemoveContainerAction', 'DockerImageRemoveContainerEvent'),
    ],
)
def test_release_and_remove_container_emit_events(
    action_name: str,
    event_name: str,
) -> None:
    """Release and remove-container emit their events regardless of image type."""
    module = _reducer_module()
    state = _image_state(module)

    result = module.image_reducer(
        state,
        getattr(module, action_name)(image='test-image'),
    )

    assert any(
        isinstance(event, getattr(module, event_name))
        for event in (result.events or [])
    )


def test_image_registers_on_combine_reducer_init() -> None:
    """A per-image init with a label builds ImageState and a register event."""
    module = _reducer_module()

    result = module.image_reducer(
        None,
        module.CombineReducerInitAction(
            combine_reducers_id='docker',
            key='reg-image',
            payload={'label': 'Registered', 'instructions': 'hold QR'},
        ),
    )

    assert result.state.id == 'reg-image'
    assert result.state.label == 'Registered'
    assert result.state.instructions == 'hold QR'
    assert any(
        isinstance(event, module.DockerImageRegisterAppEvent)
        and event.image == 'reg-image'
        for event in (result.events or [])
    )


def test_image_unhandled_action_returns_state_unchanged() -> None:
    """An image action with no dedicated case leaves the state untouched."""
    module = _reducer_module()
    state = _image_state(module)

    assert module.image_reducer(state, module.DockerImageAction(image='test-image')) \
        is state
