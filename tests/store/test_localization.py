"""Tests for the localization store slice and reducer."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from ubo_app.store.services.localization import (
    LanguageCode,
    LocalizationSetLanguageAction,
    LocalizationState,
    _load_language,
    language_label,
)


def _state_path() -> Path:
    """Return the live ``PERSISTENT_STORE_PATH`` (post conftest monkey-patch).

    Imported lazily inside each test so the autouse ``_persistent_store``
    fixture's monkey-patch is in effect — a module-top
    ``from ubo_app.constants import PERSISTENT_STORE_PATH`` would bind to
    the unpatched production path and clobber the user's real
    ``~/Library/Application Support/ubo/state.json``.
    """
    import ubo_app.constants

    return ubo_app.constants.PERSISTENT_STORE_PATH

if TYPE_CHECKING:
    import pytest
    from redux import BaseAction

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/010-localization'


class LocalizationReducer(Protocol):
    """Protocol for the localization reducer."""

    __globals__: dict[str, type[BaseAction]]

    def __call__(
        self,
        state: LocalizationState | None,
        action: BaseAction,
    ) -> LocalizationState:
        """Reduce a localization state with one action."""
        ...


def _load_localization_reducer(
    monkeypatch: pytest.MonkeyPatch,
) -> LocalizationReducer:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'localization_service_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast('LocalizationReducer', module.reducer)


def _init_action(reducer: LocalizationReducer) -> BaseAction:
    init_action_type = cast('type[BaseAction]', reducer.__globals__['InitAction'])
    return init_action_type()


def test_default_language_is_english() -> None:
    """Out of the box (no persisted value) the system language is English."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({}))

    loaded = read_from_persistent_store(
        key='localization:language',
        default=LanguageCode.EN,
        mapper=_load_language,
    )
    assert loaded == LanguageCode.EN


def test_load_language_falls_back_to_english_on_bad_input() -> None:
    """Unknown / garbage values resolve to English so the device stays usable."""
    assert _load_language('not_a_language') == LanguageCode.EN
    assert _load_language(None) == LanguageCode.EN
    assert _load_language(42) == LanguageCode.EN


def test_load_language_round_trips_known_codes() -> None:
    """Known string codes deserialize back to their enum values."""
    for code in LanguageCode:
        assert _load_language(code.value) == code


def test_language_label_known_codes() -> None:
    """Every enum value has a non-empty human-readable label."""
    for code in LanguageCode:
        assert language_label(code)


def test_reducer_sets_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dispatching ``LocalizationSetLanguageAction`` updates state."""
    from redux import CompleteReducerResult

    reducer = _load_localization_reducer(monkeypatch)
    state = cast('LocalizationState', reducer(None, _init_action(reducer)))

    # Pick any language other than the current one. The field default is
    # seeded from the on-disk persisted value at module-import time, so the
    # initial language isn't guaranteed to be English in a dev environment
    # where the real app has run.
    target = next(code for code in LanguageCode if code != state.language)

    result = reducer(state, LocalizationSetLanguageAction(language=target))
    assert isinstance(result, CompleteReducerResult)
    new_state = cast('LocalizationState', result.state)
    assert new_state.language == target


def test_reducer_noop_when_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting the same language is a no-op — no event is emitted."""
    reducer = _load_localization_reducer(monkeypatch)
    state = cast('LocalizationState', reducer(None, _init_action(reducer)))

    result = reducer(
        state,
        LocalizationSetLanguageAction(language=state.language),
    )
    # No event = bare state returned (not CompleteReducerResult)
    assert result is state


def test_persisted_language_round_trips_through_file() -> None:
    """A language written to ``state.json`` is read back on next process boot.

    Calls ``read_from_persistent_store`` directly because in production the
    function runs once at module-import time as the default for the
    ``LocalizationState.language`` field — same path the app takes on every
    restart, but not reachable via ``LocalizationState()`` after the module
    is already cached in ``sys.modules``.
    """
    from ubo_app.utils.persistent_store import read_from_persistent_store

    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({'localization:language': 'de'}))

    loaded = read_from_persistent_store(
        key='localization:language',
        default=LanguageCode.EN,
        mapper=_load_language,
    )
    assert loaded == LanguageCode.DE


def test_persisted_unknown_language_falls_back_to_english() -> None:
    """A stale / corrupted persisted value never bricks the device."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps({'localization:language': 'klingon'}),
    )

    loaded = read_from_persistent_store(
        key='localization:language',
        default=LanguageCode.EN,
        mapper=_load_language,
    )
    assert loaded == LanguageCode.EN


def test_persisted_missing_key_uses_default() -> None:
    """When ``state.json`` exists but has no language key, default applies."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({'something_else': True}))

    loaded = read_from_persistent_store(
        key='localization:language',
        default=LanguageCode.EN,
        mapper=_load_language,
    )
    assert loaded == LanguageCode.EN
