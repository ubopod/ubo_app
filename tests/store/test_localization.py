"""Tests for the localization store slice and reducer.

Class-identity discipline: integration tests earlier in the suite wipe
``sys.modules`` (see ``tests/fixtures/app.py``). The loader explicitly
``importlib.reload``s ``ubo_app.store.services.localization`` before
``exec_module``'ing the reducer, and tests pull every action / enum /
helper from the returned namespace — never from top-level imports.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from redux import BaseAction

    # Static-only — see ``_load_localization`` for why we don't bind the
    # state class at module top level at runtime.
    from ubo_app.store.services.localization import LocalizationState


SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/010-localization'


def _state_path() -> Path:
    """Return the live ``PERSISTENT_STORE_PATH`` (post conftest monkey-patch).

    Imported lazily inside each test so the autouse ``_persistent_store``
    fixture's monkey-patch is in effect.
    """
    import ubo_app.constants

    return ubo_app.constants.PERSISTENT_STORE_PATH


def _load_localization(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the localization reducer + namespace of public classes."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())

    from ubo_app.store.services import localization as localization_module

    localization_module = importlib.reload(localization_module)

    spec = importlib.util.spec_from_file_location(
        'localization_service_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        reducer=module.reducer,
        LanguageCode=localization_module.LanguageCode,
        LocalizationSetLanguageAction=(
            localization_module.LocalizationSetLanguageAction
        ),
        LocalizationState=localization_module.LocalizationState,
        load_language=localization_module._load_language,  # noqa: SLF001
        language_label=localization_module.language_label,
    )


def _init_action(ns: SimpleNamespace) -> BaseAction:
    init_action_type = cast(
        'type[BaseAction]',
        ns.reducer.__globals__['InitAction'],
    )
    return init_action_type()


def test_default_language_is_english(monkeypatch: pytest.MonkeyPatch) -> None:
    """Out of the box (no persisted value) the system language is English."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_localization(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({}))

    loaded = read_from_persistent_store(
        key='localization:language',
        default=ns.LanguageCode.EN,
        mapper=ns.load_language,
    )
    assert loaded == ns.LanguageCode.EN


def test_load_language_falls_back_to_english_on_bad_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown / garbage values resolve to English so the device stays usable."""
    ns = _load_localization(monkeypatch)
    assert ns.load_language('not_a_language') == ns.LanguageCode.EN
    assert ns.load_language(None) == ns.LanguageCode.EN
    assert ns.load_language(42) == ns.LanguageCode.EN


def test_load_language_round_trips_known_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known string codes deserialize back to their enum values."""
    ns = _load_localization(monkeypatch)
    for code in ns.LanguageCode:
        assert ns.load_language(code.value) == code


def test_language_label_known_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every enum value has a non-empty human-readable label."""
    ns = _load_localization(monkeypatch)
    for code in ns.LanguageCode:
        assert ns.language_label(code)


def test_reducer_sets_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dispatching ``LocalizationSetLanguageAction`` updates state."""
    from redux import CompleteReducerResult

    ns = _load_localization(monkeypatch)
    state = cast('LocalizationState', ns.reducer(None, _init_action(ns)))

    # Pick any language other than the current one. The field default is
    # seeded from the on-disk persisted value at module-import time, so the
    # initial language isn't guaranteed to be English in a dev environment
    # where the real app has run.
    target = next(code for code in ns.LanguageCode if code != state.language)

    result = ns.reducer(state, ns.LocalizationSetLanguageAction(language=target))
    assert isinstance(result, CompleteReducerResult)
    new_state = cast('LocalizationState', result.state)
    assert new_state.language == target


def test_reducer_noop_when_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting the same language is a no-op — no event is emitted."""
    ns = _load_localization(monkeypatch)
    state = cast('LocalizationState', ns.reducer(None, _init_action(ns)))

    result = ns.reducer(
        state,
        ns.LocalizationSetLanguageAction(language=state.language),
    )
    # No event = bare state returned (not CompleteReducerResult)
    assert result is state


def test_persisted_language_round_trips_through_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A language written to ``state.json`` is read back on next process boot."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_localization(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({'localization:language': 'de'}))

    loaded = read_from_persistent_store(
        key='localization:language',
        default=ns.LanguageCode.EN,
        mapper=ns.load_language,
    )
    assert loaded == ns.LanguageCode.DE


def test_persisted_unknown_language_falls_back_to_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale / corrupted persisted value never bricks the device."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_localization(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps({'localization:language': 'klingon'}),
    )

    loaded = read_from_persistent_store(
        key='localization:language',
        default=ns.LanguageCode.EN,
        mapper=ns.load_language,
    )
    assert loaded == ns.LanguageCode.EN


def test_persisted_missing_key_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``state.json`` exists but has no language key, default applies."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_localization(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({'something_else': True}))

    loaded = read_from_persistent_store(
        key='localization:language',
        default=ns.LanguageCode.EN,
        mapper=ns.load_language,
    )
    assert loaded == ns.LanguageCode.EN


def test_none_state_without_init_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-init action against a None state is an initialization error."""
    from redux import InitializationActionError

    ns = _load_localization(monkeypatch)

    with pytest.raises(InitializationActionError):
        ns.reducer(None, ns.LocalizationSetLanguageAction(language=ns.LanguageCode.EN))


def test_unhandled_action_returns_state_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An action matching no case leaves the state untouched."""
    ns = _load_localization(monkeypatch)
    state = ns.LocalizationState(language=ns.LanguageCode.EN)

    assert ns.reducer(state, _init_action(ns)) is state
