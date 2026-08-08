"""Tests for user-managed assistant system prompts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pytest

from ubo_app.store.services.assistant import (
    DEFAULT_SYSTEM_PROMPT_ID,
    SystemPrompt,
    _load_system_prompts,
    compose_active_system_prompt,
)

if TYPE_CHECKING:
    from types import ModuleType

    from redux import BaseAction

    from ubo_app.store.services.assistant import AssistantState

SERVICE_PATH = Path(__file__).parents[2] / 'ubo_app/services/090-assistant'


@pytest.fixture(autouse=True)
def _isolated_persistent_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep the developer's own prompts out of these tests' initial state."""
    store_path = tmp_path / 'state.json'
    monkeypatch.setattr('ubo_app.constants.PERSISTENT_STORE_PATH', store_path)
    monkeypatch.setattr(
        'ubo_app.utils.persistent_store.PERSISTENT_STORE_PATH',
        store_path,
    )


class AssistantReducer(Protocol):
    """Protocol for reducer behavior exercised by these tests."""

    __globals__: dict[str, type[BaseAction]]

    def __call__(
        self,
        state: AssistantState | None,
        action: BaseAction,
    ) -> AssistantState:
        """Reduce an assistant state with one action."""
        ...


def _load_assistant_reducer(monkeypatch: pytest.MonkeyPatch) -> AssistantReducer:
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    spec = importlib.util.spec_from_file_location(
        'assistant_service_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast('AssistantReducer', module.reducer)


def _assistant_types() -> ModuleType:
    return sys.modules['ubo_app.store.services.assistant']


def _init_action(reducer: AssistantReducer) -> BaseAction:
    init_action_type = cast('type[BaseAction]', reducer.__globals__['InitAction'])
    return init_action_type()


def _add(
    reducer: AssistantReducer,
    state: AssistantState,
    prompt_id: str,
    label: str,
    content: str,
) -> AssistantState:
    return cast(
        'AssistantState',
        reducer(
            state,
            _assistant_types().AssistantAddSystemPromptAction(
                prompt_id=prompt_id,
                label=label,
                content=content,
            ),
        ),
    )


def _toggle(
    reducer: AssistantReducer,
    state: AssistantState,
    prompt_id: str,
) -> AssistantState:
    return cast(
        'AssistantState',
        reducer(
            state,
            _assistant_types().AssistantToggleSystemPromptAction(
                prompt_id=prompt_id,
            ),
        ),
    )


def test_malformed_system_prompts_falls_back_to_empty() -> None:
    """Malformed persisted prompt data does not break state startup."""
    assert _load_system_prompts('{') == ()
    assert _load_system_prompts('{"id": "x"}') == ()
    assert _load_system_prompts('[{"label": "no id"}, 42]') == ()
    assert _load_system_prompts(
        '[{"id": "pirate", "label": "Pirate", "content": "Arr.",'
        ' "is_enabled": true}]',
    ) == (
        SystemPrompt(id='pirate', label='Pirate', content='Arr.', is_enabled=True),
    )


def test_load_system_prompts_defaults_enabled_to_false() -> None:
    """A stored entry without the flag is restored disabled, not enabled."""
    assert _load_system_prompts(
        '[{"id": "pirate", "label": "Pirate", "content": "Arr."}]',
    ) == (
        SystemPrompt(id='pirate', label='Pirate', content='Arr.', is_enabled=False),
    )


def test_compose_joins_only_enabled_non_empty_prompts() -> None:
    """Composition skips disabled and whitespace-only prompts."""
    prompts = (
        SystemPrompt(id='a', label='A', content='First.', is_enabled=True),
        SystemPrompt(id='b', label='B', content='Second.', is_enabled=False),
        SystemPrompt(id='c', label='C', content='   ', is_enabled=True),
        SystemPrompt(id='d', label='D', content='Third.', is_enabled=True),
    )
    assert compose_active_system_prompt(prompts) == 'First.\n\nThird.'


def test_initial_state_enables_only_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh install has the built-in prompt on and nothing else."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))

    assert state.system_prompts == ()
    assert state.is_default_system_prompt_enabled is True
    assert state.active_system_prompt == ''


def test_added_prompt_starts_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A newly added prompt takes effect without a second toggle."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))

    state = _add(reducer, state, 'pirate', 'Pirate', 'Answer like a pirate.')

    assert state.system_prompts == (
        SystemPrompt(
            id='pirate',
            label='Pirate',
            content='Answer like a pirate.',
            is_enabled=True,
        ),
    )
    assert state.active_system_prompt == 'Answer like a pirate.'


def test_editing_upserts_and_preserves_enabled_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Editing reuses the id, replaces the entry and keeps it disabled if it was."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))

    state = _add(reducer, state, 'pirate', 'Pirate', 'Answer like a pirate.')
    state = _toggle(reducer, state, 'pirate')
    assert state.system_prompts[0].is_enabled is False

    state = _add(reducer, state, 'pirate', 'Buccaneer', 'Answer like a buccaneer.')

    assert len(state.system_prompts) == 1
    assert state.system_prompts[0].label == 'Buccaneer'
    assert state.system_prompts[0].content == 'Answer like a buccaneer.'
    # Still off, so it must not have crept back into the composed prompt.
    assert state.system_prompts[0].is_enabled is False
    assert state.active_system_prompt == ''


def test_multiple_prompts_compose_in_insertion_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several prompts can be enabled at once and are joined in order."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))

    state = _add(reducer, state, 'terse', 'Terse', 'Be terse.')
    state = _add(reducer, state, 'pirate', 'Pirate', 'Answer like a pirate.')

    assert state.active_system_prompt == 'Be terse.\n\nAnswer like a pirate.'

    state = _toggle(reducer, state, 'terse')
    assert state.active_system_prompt == 'Answer like a pirate.'


def test_toggling_default_leaves_custom_prompts_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The built-in prompt is a separate flag, not an entry in the list."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))
    state = _add(reducer, state, 'terse', 'Terse', 'Be terse.')

    state = _toggle(reducer, state, DEFAULT_SYSTEM_PROMPT_ID)

    assert state.is_default_system_prompt_enabled is False
    assert state.active_system_prompt == 'Be terse.'
    assert len(state.system_prompts) == 1

    state = _toggle(reducer, state, DEFAULT_SYSTEM_PROMPT_ID)
    assert state.is_default_system_prompt_enabled is True


def test_removing_a_prompt_drops_it_from_the_composed_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removal is surgical and recomputes the derived prompt."""
    reducer = _load_assistant_reducer(monkeypatch)
    state = cast('AssistantState', reducer(None, _init_action(reducer)))
    state = _add(reducer, state, 'terse', 'Terse', 'Be terse.')
    state = _add(reducer, state, 'pirate', 'Pirate', 'Answer like a pirate.')

    state = cast(
        'AssistantState',
        reducer(
            state,
            _assistant_types().AssistantRemoveSystemPromptAction(prompt_id='terse'),
        ),
    )

    assert [prompt.id for prompt in state.system_prompts] == ['pirate']
    assert state.active_system_prompt == 'Answer like a pirate.'
