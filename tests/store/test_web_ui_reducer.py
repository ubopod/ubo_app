"""Tests for the web-ui reducer's input-demand behavior.

The hotspot lifecycle now lives in the wifi service (see
``test_wifi_hotspot_reducer.py``); the web-ui reducer only tracks active inputs.
Resolving/cancelling an input clears it *without* tearing down the hotspot, so
multi-step web flows keep the hotspot up across steps.

Uses the same ``sys.path`` loader discipline as ``test_camera_reducer.py`` so the
reducer's match-case and the test's constructed actions reference the same class
objects even after an integration test wipes ``sys.modules``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from redux import CompleteReducerResult

if TYPE_CHECKING:
    from collections.abc import Callable


def _import_types_and_reducer() -> tuple[tuple[Any, ...], Callable[..., Any]]:
    modules_before = set(sys.modules)

    from ubo_app.store.input.types import (
        InputCancelAction,
        InputDemandAction,
        WebUIInputDescription,
    )
    from ubo_app.store.services.web_ui import (
        WebUIInitializeEvent,
        WebUIState,
    )

    service_dir = str(
        Path(__file__).resolve().parents[2]
        / 'ubo_app'
        / 'services'
        / '090-web-ui',
    )
    if service_dir not in sys.path:
        sys.path.insert(0, service_dir)

    from reducer import reducer  # type: ignore[import-not-found]

    for mod in set(sys.modules) - modules_before:
        del sys.modules[mod]

    return (
        InputCancelAction,
        InputDemandAction,
        WebUIInputDescription,
        WebUIInitializeEvent,
        WebUIState,
    ), reducer


(
    InputCancelAction,
    InputDemandAction,
    WebUIInputDescription,
    WebUIInitializeEvent,
    WebUIState,
), reducer = _import_types_and_reducer()


def test_demand_emits_initialize_event() -> None:
    """Demanding a web input registers it and emits WebUIInitializeEvent."""
    description = WebUIInputDescription(id='abc')
    state = WebUIState(active_inputs=[])

    result = reducer(state, InputDemandAction(description=description))

    assert isinstance(result, CompleteReducerResult)
    assert any(isinstance(event, WebUIInitializeEvent) for event in result.events or [])
    assert result.state.active_inputs == [description]


def test_resolving_last_input_clears_it() -> None:
    """Resolving the final active input clears it; no hotspot logic remains here."""
    description = WebUIInputDescription(id='abc')
    state = WebUIState(active_inputs=[description])

    result = reducer(state, InputCancelAction(id='abc'))

    assert isinstance(result, CompleteReducerResult)
    assert result.state.active_inputs == []


def test_init_action_builds_empty_state() -> None:
    """A None state plus InitAction yields an empty active-inputs state."""
    from redux import InitAction

    result = reducer(None, InitAction())

    assert result.active_inputs == []


def test_none_state_without_init_raises() -> None:
    """Any non-init action against a None state is an initialization error."""
    import pytest
    from redux import InitializationActionError

    with pytest.raises(InitializationActionError):
        reducer(None, InputDemandAction(description=WebUIInputDescription(id='x')))


def test_unhandled_action_returns_state_unchanged() -> None:
    """An action matching no case leaves the state untouched."""
    from redux import InitAction

    state = WebUIState(active_inputs=[])

    assert reducer(state, InitAction()) is state
