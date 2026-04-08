"""Tests for the file system reducer.

Focuses on selector_depth tracking, stack cleanup on selection,
and depth reset in pop_queue / InputDemandAction.

NOTE: The file system service uses relative imports (from constants import ...,
from file_application import ...). We add the service directory to sys.path
before importing the reducer.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest
from redux import CompleteReducerResult, InitAction

from ubo_app.store.core.types import StackPopAction
from ubo_app.store.input.types import (
    InputDemandAction,
    InputMethod,
    InputResolveAction,
    PathInputDescription,
)
from ubo_app.store.services.file_system import (
    FileSystemReportSelectionAction,
    FileSystemSelectorCleanupEvent,
    FileSystemSelectorPushedAction,
    FileSystemState,
    PathSelectorConfig,
)

# Add the service directory to sys.path so relative imports work
_SERVICE_DIR = str(
    Path(__file__).resolve().parents[2]
    / 'ubo_app'
    / 'services'
    / '090-file-system',
)
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from reducer import (  # noqa: E402
    pop_queue,
    reducer,
)


def _init_state() -> FileSystemState:
    """Initialize a fresh FileSystemState via the reducer."""
    result = reducer(None, InitAction())
    assert isinstance(result, FileSystemState)
    return result


def _make_description(*, id_: str = 'test-input') -> PathInputDescription:
    """Create a test PathInputDescription."""
    return PathInputDescription(
        id=id_,
        title='Test',
        prompt='Select a path',
        selector_config=PathSelectorConfig(
            accepts_directories=True,
            accepts_files=False,
        ),
    )


def _demand_state(
    state: FileSystemState | None = None,
    *,
    id_: str = 'test-input',
) -> FileSystemState:
    """Return state after an InputDemandAction with a PathInputDescription."""
    if state is None:
        state = _init_state()
    result = reducer(state, InputDemandAction(description=_make_description(id_=id_)))
    assert isinstance(result, CompleteReducerResult)
    return result.state


class TestSelectorDepthTracking:
    """Tests for selector_depth state management."""

    def test_initial_state_zero_depth(self) -> None:
        """New state has selector_depth=0."""
        state = _init_state()
        assert state.selector_depth == 0

    def test_selector_pushed_increments_depth(self) -> None:
        """FileSystemSelectorPushedAction increments selector_depth by 1."""
        state = _init_state()
        result = reducer(state, FileSystemSelectorPushedAction())
        assert isinstance(result, FileSystemState)
        assert result.selector_depth == 1

    def test_multiple_pushes_increment(self) -> None:
        """Multiple pushes accumulate: depth should equal push count."""
        state = _init_state()
        for _ in range(4):
            result = reducer(state, FileSystemSelectorPushedAction())
            assert isinstance(result, FileSystemState)
            state = result

        expected_depth = 4
        assert state.selector_depth == expected_depth

    def test_input_demand_resets_depth(self) -> None:
        """InputDemandAction with PathInputDescription resets selector_depth to 0."""
        state = _init_state()
        state = replace(state, selector_depth=3)
        result = reducer(
            state,
            InputDemandAction(description=_make_description()),
        )
        assert isinstance(result, CompleteReducerResult)
        assert result.state.selector_depth == 0


class TestSelectionCleanup:
    """Tests for stack cleanup on FileSystemReportSelectionAction."""

    def test_selection_returns_stack_pop(self) -> None:
        """When selector_depth > 0, returned actions include StackPopAction."""
        state = _demand_state()
        state = replace(state, selector_depth=3)
        result = reducer(
            state,
            FileSystemReportSelectionAction(path='/tmp/dest'),  # noqa: S108
        )
        assert isinstance(result, CompleteReducerResult)
        assert result.actions is not None

        pop_actions = [a for a in result.actions if isinstance(a, StackPopAction)]
        assert len(pop_actions) == 1
        expected_count = 3
        assert pop_actions[0].count == expected_count

    def test_selection_resets_depth(self) -> None:
        """After selection, selector_depth is reset to 0."""
        state = _demand_state()
        state = replace(state, selector_depth=5)
        result = reducer(
            state,
            FileSystemReportSelectionAction(path='/tmp/dest'),  # noqa: S108
        )
        assert isinstance(result, CompleteReducerResult)
        assert result.state.selector_depth == 0

    def test_selection_with_zero_depth_no_pop(self) -> None:
        """When selector_depth=0, no StackPopAction is included."""
        state = _demand_state()
        assert state.selector_depth == 0
        result = reducer(
            state,
            FileSystemReportSelectionAction(path='/tmp/dest'),  # noqa: S108
        )
        assert isinstance(result, CompleteReducerResult)
        assert result.actions is not None

        pop_actions = [a for a in result.actions if isinstance(a, StackPopAction)]
        assert len(pop_actions) == 0

    def test_selection_with_empty_queue_noop(self) -> None:
        """Selection with empty queue returns state unchanged."""
        state = _init_state()
        result = reducer(
            state,
            FileSystemReportSelectionAction(path='/tmp/dest'),  # noqa: S108
        )
        assert result is state


class TestPopQueueResetsDepth:
    """Tests for pop_queue depth reset."""

    def test_pop_queue_resets_depth(self) -> None:
        """pop_queue() resets selector_depth to 0."""
        state = FileSystemState(
            queue=[_make_description()],
            selector_depth=5,
        )
        result = pop_queue(state)
        assert isinstance(result, CompleteReducerResult)
        assert result.state.selector_depth == 0

    def test_input_resolve_resets_depth(self) -> None:
        """InputResolveAction triggers pop_queue which resets selector_depth."""
        state = _demand_state()
        state = replace(state, selector_depth=3)
        result = reducer(state, InputResolveAction(id='test-input'))
        assert isinstance(result, CompleteReducerResult)
        assert result.state.selector_depth == 0

    def test_pop_queue_emits_stack_pop_when_depth_positive(self) -> None:
        """pop_queue dispatches StackPopAction when selector_depth > 0."""
        state = FileSystemState(
            queue=[_make_description()],
            selector_depth=4,
        )
        result = pop_queue(state)
        assert isinstance(result, CompleteReducerResult)
        pop_actions = [a for a in result.actions if isinstance(a, StackPopAction)]
        assert len(pop_actions) == 1
        expected_count = 4
        assert pop_actions[0].count == expected_count

    def test_pop_queue_no_stack_pop_when_depth_zero(self) -> None:
        """pop_queue does not dispatch StackPopAction when selector_depth is 0."""
        state = FileSystemState(
            queue=[_make_description()],
            selector_depth=0,
        )
        result = pop_queue(state)
        assert isinstance(result, CompleteReducerResult)
        pop_actions = [a for a in result.actions if isinstance(a, StackPopAction)]
        assert len(pop_actions) == 0

    def test_pop_queue_emits_cleanup_event_when_depth_positive(self) -> None:
        """pop_queue emits FileSystemSelectorCleanupEvent when selector_depth > 0."""
        state = FileSystemState(
            queue=[_make_description()],
            selector_depth=2,
        )
        result = pop_queue(state)
        assert isinstance(result, CompleteReducerResult)
        cleanup_events = [
            e for e in result.events if isinstance(e, FileSystemSelectorCleanupEvent)
        ]
        assert len(cleanup_events) == 1

    def test_pop_queue_no_cleanup_event_when_depth_zero(self) -> None:
        """pop_queue does not emit cleanup event when selector_depth is 0."""
        state = FileSystemState(
            queue=[_make_description()],
            selector_depth=0,
        )
        result = pop_queue(state)
        assert isinstance(result, CompleteReducerResult)
        cleanup_events = [
            e for e in result.events if isinstance(e, FileSystemSelectorCleanupEvent)
        ]
        assert len(cleanup_events) == 0


class TestSelectionInputProvide:
    """Tests for InputProvideAction generation on selection."""

    def test_selection_returns_input_provide(self) -> None:
        """Selection returns InputProvideAction with correct id and value."""
        from ubo_app.store.input.types import InputProvideAction

        state = _demand_state()
        result = reducer(
            state,
            FileSystemReportSelectionAction(path='/tmp/dest'),  # noqa: S108
        )
        assert isinstance(result, CompleteReducerResult)
        assert result.actions is not None

        provide_actions = [
            a for a in result.actions if isinstance(a, InputProvideAction)
        ]
        assert len(provide_actions) == 1
        assert provide_actions[0].id == 'test-input'
        assert provide_actions[0].value == '/tmp/dest'  # noqa: S108
        assert provide_actions[0].result is not None
        assert provide_actions[0].result.method == InputMethod.PATH_SELECTOR

    @pytest.mark.parametrize('depth', [0, 1, 5])
    def test_selection_emits_cleanup_event(self, depth: int) -> None:
        """Selection emits FileSystemSelectorCleanupEvent."""
        state = _demand_state()
        state = replace(state, selector_depth=depth)
        result = reducer(
            state,
            FileSystemReportSelectionAction(path='/tmp/dest'),  # noqa: S108
        )
        assert isinstance(result, CompleteReducerResult)
        cleanup_events = [
            e for e in result.events if isinstance(e, FileSystemSelectorCleanupEvent)
        ]
        assert len(cleanup_events) == 1


class TestCancelCleanup:
    """Tests for selector cleanup on cancel (InputResolveAction/InputCancelAction)."""

    def test_cancel_with_depth_emits_stack_pop(self) -> None:
        """Cancelling with selector_depth > 0 dispatches StackPopAction."""
        state = _demand_state()
        state = replace(state, selector_depth=3)
        result = reducer(state, InputResolveAction(id='test-input'))
        assert isinstance(result, CompleteReducerResult)
        pop_actions = [a for a in result.actions if isinstance(a, StackPopAction)]
        assert len(pop_actions) == 1
        expected_count = 3
        assert pop_actions[0].count == expected_count

    def test_cancel_with_depth_emits_cleanup_event(self) -> None:
        """Cancelling with selector_depth > 0 emits FileSystemSelectorCleanupEvent."""
        state = _demand_state()
        state = replace(state, selector_depth=2)
        result = reducer(state, InputResolveAction(id='test-input'))
        assert isinstance(result, CompleteReducerResult)
        cleanup_events = [
            e for e in result.events if isinstance(e, FileSystemSelectorCleanupEvent)
        ]
        assert len(cleanup_events) == 1

    def test_cancel_with_zero_depth_no_pop(self) -> None:
        """Cancelling with selector_depth=0 does not dispatch StackPopAction."""
        state = _demand_state()
        assert state.selector_depth == 0
        result = reducer(state, InputResolveAction(id='test-input'))
        assert isinstance(result, CompleteReducerResult)
        pop_actions = [a for a in result.actions if isinstance(a, StackPopAction)]
        assert len(pop_actions) == 0

    def test_cancel_with_zero_depth_no_cleanup_event(self) -> None:
        """Cancelling with selector_depth=0 does not emit cleanup event."""
        state = _demand_state()
        assert state.selector_depth == 0
        result = reducer(state, InputResolveAction(id='test-input'))
        assert isinstance(result, CompleteReducerResult)
        cleanup_events = [
            e for e in result.events if isinstance(e, FileSystemSelectorCleanupEvent)
        ]
        assert len(cleanup_events) == 0
