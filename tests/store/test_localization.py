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
        LocationSource=localization_module.LocationSource,
        LocationInfo=localization_module.LocationInfo,
        WeatherCondition=localization_module.WeatherCondition,
        LocalizationSetLocationAction=(
            localization_module.LocalizationSetLocationAction
        ),
        LocalizationResetLocationAction=(
            localization_module.LocalizationResetLocationAction
        ),
        LocalizationUpdateWeatherAction=(
            localization_module.LocalizationUpdateWeatherAction
        ),
        LocalizationRefreshWeatherAction=(
            localization_module.LocalizationRefreshWeatherAction
        ),
        LocalizationSpeakTimeAction=localization_module.LocalizationSpeakTimeAction,
        LocalizationSpeakDateAction=localization_module.LocalizationSpeakDateAction,
        LocalizationSpeakWeatherAction=(
            localization_module.LocalizationSpeakWeatherAction
        ),
        LocalizationLocationChangedEvent=(
            localization_module.LocalizationLocationChangedEvent
        ),
        LocalizationLocationResetEvent=(
            localization_module.LocalizationLocationResetEvent
        ),
        LocalizationWeatherRefreshRequestedEvent=(
            localization_module.LocalizationWeatherRefreshRequestedEvent
        ),
        LocalizationSpeakTimeEvent=localization_module.LocalizationSpeakTimeEvent,
        LocalizationSpeakDateEvent=localization_module.LocalizationSpeakDateEvent,
        LocalizationSpeakWeatherEvent=(
            localization_module.LocalizationSpeakWeatherEvent
        ),
        load_location=localization_module._load_location,  # noqa: SLF001
        load_location_source=localization_module._load_location_source,  # noqa: SLF001
        UnitSystem=localization_module.UnitSystem,
        unit_system_label=localization_module.unit_system_label,
        load_unit_system=localization_module._load_unit_system,  # noqa: SLF001
        LocalizationSetUnitSystemAction=(
            localization_module.LocalizationSetUnitSystemAction
        ),
        LocalizationUnitSystemChangedEvent=(
            localization_module.LocalizationUnitSystemChangedEvent
        ),
    )


def _berlin(ns: SimpleNamespace) -> object:
    return ns.LocationInfo(
        latitude=52.52,
        longitude=13.405,
        city='Berlin',
        country='Germany',
        country_code='DE',
        timezone='Europe/Berlin',
    )


def _lisbon(ns: SimpleNamespace) -> object:
    return ns.LocationInfo(
        latitude=38.7223,
        longitude=-9.1393,
        city='Lisbon',
        country='Portugal',
        country_code='PT',
        timezone='Europe/Lisbon',
    )


def _base_state(ns: SimpleNamespace, **kwargs: object) -> LocalizationState:
    """Build a state with explicit defaults, so no persisted file leaks in."""
    fields: dict[str, object] = {
        'language': ns.LanguageCode.EN,
        'location': None,
        'location_source': ns.LocationSource.IP,
        'public_ip': None,
        'unit_system': ns.UnitSystem.AUTO,
        'weather': None,
    }
    fields.update(kwargs)
    return cast('LocalizationState', ns.LocalizationState(**fields))


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


def test_set_location_stores_location_and_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An IP-detected location lands in state and announces itself."""
    from redux import CompleteReducerResult

    ns = _load_localization(monkeypatch)
    state = _base_state(ns)

    result = ns.reducer(
        state,
        ns.LocalizationSetLocationAction(
            location=_berlin(ns),
            source=ns.LocationSource.IP,
            public_ip='198.51.100.7',
        ),
    )

    assert isinstance(result, CompleteReducerResult)
    new_state = cast('LocalizationState', result.state)
    assert new_state.location == _berlin(ns)
    assert new_state.location_source == ns.LocationSource.IP
    assert new_state.public_ip == '198.51.100.7'
    assert result.events is not None
    assert isinstance(result.events[0], ns.LocalizationLocationChangedEvent)


def test_ip_location_never_overwrites_a_manual_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The automatic detector must not clobber what the user set by hand."""
    ns = _load_localization(monkeypatch)
    state = _base_state(
        ns,
        location=_lisbon(ns),
        location_source=ns.LocationSource.MANUAL,
    )

    result = ns.reducer(
        state,
        ns.LocalizationSetLocationAction(
            location=_berlin(ns),
            source=ns.LocationSource.IP,
            public_ip='198.51.100.7',
        ),
    )

    assert result is state


def test_manual_location_flips_source_and_clears_stale_weather(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting a new location by hand invalidates the previous location's weather."""
    from redux import CompleteReducerResult

    ns = _load_localization(monkeypatch)
    state = _base_state(
        ns,
        location=_berlin(ns),
        location_source=ns.LocationSource.IP,
        weather=ns.WeatherCondition(
            symbol_code='clearsky_day',
            temperature_celsius=21.0,
            expires_at=1_000_000.0,
        ),
    )

    result = ns.reducer(
        state,
        ns.LocalizationSetLocationAction(
            location=_lisbon(ns),
            source=ns.LocationSource.MANUAL,
        ),
    )

    assert isinstance(result, CompleteReducerResult)
    new_state = cast('LocalizationState', result.state)
    assert new_state.location == _lisbon(ns)
    assert new_state.location_source == ns.LocationSource.MANUAL
    assert new_state.weather is None


def test_reset_clears_location_and_returns_to_automatic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reset wipes the manual override so IP detection takes over again."""
    from redux import CompleteReducerResult

    ns = _load_localization(monkeypatch)
    state = _base_state(
        ns,
        location=_lisbon(ns),
        location_source=ns.LocationSource.MANUAL,
        public_ip='198.51.100.7',
        weather=ns.WeatherCondition(
            symbol_code='clearsky_day',
            temperature_celsius=21.0,
        ),
    )

    result = ns.reducer(state, ns.LocalizationResetLocationAction())

    assert isinstance(result, CompleteReducerResult)
    new_state = cast('LocalizationState', result.state)
    assert new_state.location is None
    assert new_state.location_source == ns.LocationSource.IP
    assert new_state.public_ip is None
    assert new_state.weather is None
    assert result.events is not None
    assert isinstance(result.events[0], ns.LocalizationLocationResetEvent)


def test_refresh_weather_requires_a_known_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a location there is nothing to fetch weather for."""
    from redux import CompleteReducerResult

    ns = _load_localization(monkeypatch)

    assert (
        ns.reducer(_base_state(ns), ns.LocalizationRefreshWeatherAction())
        is not None
    )
    result = ns.reducer(_base_state(ns), ns.LocalizationRefreshWeatherAction())
    assert not isinstance(result, CompleteReducerResult)

    with_location = _base_state(ns, location=_berlin(ns))
    result = ns.reducer(with_location, ns.LocalizationRefreshWeatherAction())
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert isinstance(
        result.events[0],
        ns.LocalizationWeatherRefreshRequestedEvent,
    )


def test_update_weather_replaces_the_cached_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fetched forecast lands in state, with display fields computed."""
    ns = _load_localization(monkeypatch)
    state = _base_state(ns, location=_berlin(ns), unit_system=ns.UnitSystem.METRIC)
    weather = ns.WeatherCondition(
        symbol_code='partlycloudy_day',
        temperature_celsius=18.5,
        wind_speed_mps=3.2,
        fetched_at=1_000_000.0,
        expires_at=1_001_800.0,
    )

    new_state = cast(
        'LocalizationState',
        ns.reducer(state, ns.LocalizationUpdateWeatherAction(weather=weather)),
    )

    assert new_state.weather is not None
    assert new_state.weather.symbol_code == weather.symbol_code
    assert new_state.weather.temperature_celsius == weather.temperature_celsius
    assert new_state.weather.temperature_display_value == pytest.approx(18.5)
    assert new_state.weather.temperature_display_unit == '°C'
    assert new_state.weather.wind_speed_display_value == pytest.approx(3.2 * 3.6)
    assert new_state.weather.wind_speed_display_unit == 'km/h'


def test_speak_actions_emit_snapshot_events_without_touching_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The speak actions are pure triggers — the async handler does the work."""
    from redux import CompleteReducerResult

    ns = _load_localization(monkeypatch)
    weather = ns.WeatherCondition(
        symbol_code='rain',
        temperature_celsius=11.0,
    )
    state = _base_state(ns, location=_berlin(ns), weather=weather)

    time_result = ns.reducer(state, ns.LocalizationSpeakTimeAction())
    assert isinstance(time_result, CompleteReducerResult)
    assert time_result.state is state
    assert time_result.events is not None
    assert time_result.events[0].timezone == 'Europe/Berlin'

    date_result = ns.reducer(state, ns.LocalizationSpeakDateAction())
    assert isinstance(date_result, CompleteReducerResult)
    assert date_result.events is not None
    assert date_result.events[0].timezone == 'Europe/Berlin'

    weather_result = ns.reducer(state, ns.LocalizationSpeakWeatherAction())
    assert isinstance(weather_result, CompleteReducerResult)
    assert weather_result.events is not None
    assert weather_result.events[0].weather == weather
    assert weather_result.events[0].location == _berlin(ns)


def test_speak_events_carry_none_when_location_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no location the handler still runs — it just speaks a fallback."""
    from redux import CompleteReducerResult

    ns = _load_localization(monkeypatch)
    state = _base_state(ns)

    result = ns.reducer(state, ns.LocalizationSpeakTimeAction())
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert result.events[0].timezone is None

    result = ns.reducer(state, ns.LocalizationSpeakWeatherAction())
    assert isinstance(result, CompleteReducerResult)
    assert result.events is not None
    assert result.events[0].weather is None
    assert result.events[0].location is None


def test_load_location_round_trips_and_rejects_garbage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupted persisted location degrades to "unknown", never to a crash."""
    ns = _load_localization(monkeypatch)

    loaded = ns.load_location(
        {
            'latitude': 52.52,
            'longitude': 13.405,
            'city': 'Berlin',
            'country': 'Germany',
            'country_code': 'DE',
            'timezone': 'Europe/Berlin',
        },
    )
    assert loaded == _berlin(ns)

    assert ns.load_location(None) is None
    assert ns.load_location('nonsense') is None
    assert ns.load_location({}) is None
    assert ns.load_location({'latitude': 'x', 'longitude': 1.0}) is None
    # Coordinates alone are enough — the rest is optional.
    partial = ns.load_location({'latitude': 1.0, 'longitude': 2.0})
    assert partial is not None
    assert partial.city is None


def test_load_location_source_falls_back_to_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrecognized source resolves to automatic detection."""
    ns = _load_localization(monkeypatch)

    assert ns.load_location_source('manual') == ns.LocationSource.MANUAL
    assert ns.load_location_source('ip') == ns.LocationSource.IP
    assert ns.load_location_source('garbage') == ns.LocationSource.IP
    assert ns.load_location_source(None) == ns.LocationSource.IP


def test_persisted_location_round_trips_through_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A location written to ``state.json`` is read back on next process boot."""
    from ubo_app.utils.persistent_store import read_from_persistent_store

    ns = _load_localization(monkeypatch)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(
        json.dumps(
            {
                'localization:location': {
                    'latitude': 52.52,
                    'longitude': 13.405,
                    'city': 'Berlin',
                    'country': 'Germany',
                    'country_code': 'DE',
                    'timezone': 'Europe/Berlin',
                },
                'localization:location_source': 'manual',
            },
        ),
    )

    assert (
        read_from_persistent_store(
            key='localization:location',
            default=None,
            mapper=ns.load_location,
        )
        == _berlin(ns)
    )
    assert (
        read_from_persistent_store(
            key='localization:location_source',
            default=ns.LocationSource.IP,
            mapper=ns.load_location_source,
        )
        == ns.LocationSource.MANUAL
    )


def test_load_unit_system_defaults_to_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown / garbage values resolve to Automatic so the device stays usable."""
    ns = _load_localization(monkeypatch)
    assert ns.load_unit_system('not_a_system') == ns.UnitSystem.AUTO
    assert ns.load_unit_system(None) == ns.UnitSystem.AUTO
    assert ns.load_unit_system(42) == ns.UnitSystem.AUTO
    assert ns.load_unit_system('metric') == ns.UnitSystem.METRIC
    assert ns.load_unit_system('us') == ns.UnitSystem.US


def test_unit_system_label_known_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every enum value has a non-empty human-readable label."""
    ns = _load_localization(monkeypatch)
    for system in ns.UnitSystem:
        assert ns.unit_system_label(system)


def test_reducer_sets_unit_system_and_emits_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatching ``LocalizationSetUnitSystemAction`` updates state."""
    from redux import CompleteReducerResult

    ns = _load_localization(monkeypatch)
    state = _base_state(ns, unit_system=ns.UnitSystem.AUTO)

    result = ns.reducer(
        state,
        ns.LocalizationSetUnitSystemAction(unit_system=ns.UnitSystem.US),
    )
    assert isinstance(result, CompleteReducerResult)
    new_state = cast('LocalizationState', result.state)
    assert new_state.unit_system == ns.UnitSystem.US
    assert result.events is not None
    assert isinstance(result.events[0], ns.LocalizationUnitSystemChangedEvent)
    assert result.events[0].unit_system == ns.UnitSystem.US


def test_set_unit_system_noop_when_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting the same unit system is a no-op — no event is emitted."""
    ns = _load_localization(monkeypatch)
    state = _base_state(ns, unit_system=ns.UnitSystem.METRIC)

    result = ns.reducer(
        state,
        ns.LocalizationSetUnitSystemAction(unit_system=ns.UnitSystem.METRIC),
    )
    assert result is state


def test_set_unit_system_recomputes_cached_weather_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flipping units immediately reformats already-cached weather."""
    ns = _load_localization(monkeypatch)
    weather = ns.WeatherCondition(
        symbol_code='clearsky_day',
        temperature_celsius=20.0,
        wind_speed_mps=5.0,
    )
    state = _base_state(
        ns,
        location=_berlin(ns),
        unit_system=ns.UnitSystem.METRIC,
        weather=weather,
    )

    result = ns.reducer(
        state,
        ns.LocalizationSetUnitSystemAction(unit_system=ns.UnitSystem.US),
    )
    new_state = cast('LocalizationState', result.state)
    assert new_state.weather is not None
    # 20C -> 68F, and the cached weather is kept, not cleared.
    assert new_state.weather.temperature_display_value == pytest.approx(68.0)
    assert new_state.weather.temperature_display_unit == '°F'
