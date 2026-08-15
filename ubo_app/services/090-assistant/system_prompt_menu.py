"""Settings menus for the assistant's system prompts.

Two menu levels, both rebuilt by one autorun over
``state.assistant.system_prompts`` and
``state.assistant.is_default_system_prompt_enabled``:

* ``assistant:system_prompts`` — the list. A read-only ``Default`` row toggling
  the built-in prompt, one checkbox row per user prompt, and an ``Add Prompt``
  row that opens the Web UI form.
* ``assistant:system_prompts:<id>`` — one per user prompt, with an enable
  toggle, an edit action that reopens the form pre-filled, and a delete action
  behind a confirmation.

Several prompts can be enabled at once; the reducer concatenates them into
``active_system_prompt``, which the assistant subprocess subscribes to.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ubo_app.colors import DANGER_COLOR, SUCCESS_COLOR
from ubo_app.constants.assistant import SYSTEM_PROMPT_GUIDANCE
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuGoBackAction,
    MenuItemData,
    StackPushMenuAction,
    StackPushPromptAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    DEFAULT_SYSTEM_PROMPT_ID,
    AssistantAddSystemPromptAction,
    AssistantRemoveSystemPromptAction,
    AssistantToggleSystemPromptAction,
    SystemPrompt,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.text import slugify

if TYPE_CHECKING:
    from collections.abc import Sequence

MENU_ID = 'assistant:system_prompts'
# Path segment the list menu's rows push; mirrored by the tail matcher in
# ``setup.py::_register_assistant_path_matchers``.
DETAIL_MENU_KEY_PREFIX = 'system-prompt:'

CHECKED_ICON = '󰱒'
UNCHECKED_ICON = '󰄱'

_ADD_ACTION_ID = 'assistant:system-prompt:add'
_CANCEL_ACTION_ID = 'assistant:system-prompt:cancel'
# Action ids minted per prompt on each rebuild; dropped before the next one.
_action_ids: list[str] = []


def _detail_menu_id(prompt_id: str) -> str:
    return f'{MENU_ID}:{prompt_id}'


def _notify_failure(content: str) -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='assistant:system_prompt:invalid',
                title='System Prompt',
                content=content,
                color=DANGER_COLOR,
                display_type=NotificationDisplayType.FLASH,
            ),
        ),
    )


async def _collect_prompt(existing: SystemPrompt | None) -> None:
    """Run the Web UI form and add (or update) the prompt it returns."""
    with contextlib.suppress(asyncio.CancelledError):
        _, result = await ubo_input(
            prompt='System Prompt',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='label',
                            type=InputFieldType.TEXT,
                            label='Name',
                            description='A short name, e.g. "Terse Answers"',
                            required=True,
                            default_value=existing.label if existing else None,
                        ),
                        InputFieldDescription(
                            name='content',
                            type=InputFieldType.LONG,
                            label='Prompt',
                            description=SYSTEM_PROMPT_GUIDANCE,
                            required=True,
                            default_value=existing.content if existing else None,
                        ),
                    ],
                ),
            ],
        )

        label = (result.data.get('label') or '').strip()
        content = (result.data.get('content') or '').strip()
        if not label or not content:
            return

        if existing is not None:
            # Keep the original id so a rename updates in place rather than
            # orphaning the entry and its enabled flag.
            prompt_id = existing.id
        else:
            prompt_id = slugify(label)
            if not prompt_id:
                _notify_failure('The name must contain letters or digits.')
                return
            if prompt_id in _existing_prompt_ids():
                _notify_failure(
                    f'A prompt named "{label}" already exists. '
                    'Edit it or pick another name.',
                )
                return

        store.dispatch(
            AssistantAddSystemPromptAction(
                prompt_id=prompt_id,
                label=label,
                content=content,
            ),
        )


@store.with_state(lambda state: state.assistant.system_prompts)
def _existing_prompt_ids(prompts: tuple[SystemPrompt, ...]) -> set[str]:
    return {prompt.id for prompt in prompts}


def _register_detail_menu(prompt: SystemPrompt) -> None:
    """Register the per-prompt actions and publish its detail menu."""
    toggle_action_id = f'assistant:system-prompt:toggle:{prompt.id}'
    edit_action_id = f'assistant:system-prompt:edit:{prompt.id}'
    delete_action_id = f'assistant:system-prompt:delete:{prompt.id}'
    confirm_action_id = f'assistant:system-prompt:confirm-delete:{prompt.id}'
    _action_ids.extend(
        [toggle_action_id, edit_action_id, delete_action_id, confirm_action_id],
    )

    register_action(
        toggle_action_id,
        lambda prompt_id=prompt.id: store.dispatch(
            AssistantToggleSystemPromptAction(prompt_id=prompt_id),
        ),
        allow_reregister=True,
    )
    register_action(
        edit_action_id,
        # ``create_task`` returns a Task; a non-``None`` handler result would
        # push a stray empty menu frame, so swallow it.
        lambda existing=prompt: (create_task(_collect_prompt(existing)), None)[1],
        allow_reregister=True,
    )
    register_action(
        confirm_action_id,
        # Pop the confirmation prompt *and* this prompt's now-dead detail page.
        lambda prompt_id=prompt.id: store.dispatch(
            AssistantRemoveSystemPromptAction(prompt_id=prompt_id),
            MenuGoBackAction(),
            MenuGoBackAction(),
        ),
        allow_reregister=True,
    )
    register_action(
        delete_action_id,
        lambda label=prompt.label, confirm=confirm_action_id: store.dispatch(
            StackPushPromptAction(
                title='Delete Prompt',
                prompt=f'Remove "{label}"?',
                icon='󰆴',
                # Exactly two items — the GUI client maps them onto its two
                # bottom buttons by index.
                items=(
                    MenuItemData(
                        key='yes',
                        label='Delete',
                        icon='󰆴',
                        color=DANGER_COLOR,
                        action_id=confirm,
                    ),
                    MenuItemData(
                        key='cancel',
                        label='Cancel',
                        icon='󰜺',
                        action_id=_CANCEL_ACTION_ID,
                    ),
                ),
            ),
        ),
        allow_reregister=True,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=_detail_menu_id(prompt.id),
            title='System Prompt',
            heading=prompt.label,
            sub_heading='Enabled prompts are sent together.',
            items=(
                MenuItemData(
                    key='enabled',
                    label='Enabled',
                    icon=CHECKED_ICON if prompt.is_enabled else UNCHECKED_ICON,
                    background_color=SUCCESS_COLOR if prompt.is_enabled else None,
                    action_id=toggle_action_id,
                ),
                MenuItemData(
                    key='edit',
                    label='Edit',
                    icon='󰏫',
                    action_id=edit_action_id,
                ),
                MenuItemData(
                    key='delete',
                    label='Delete',
                    icon='󰆴',
                    color=DANGER_COLOR,
                    action_id=delete_action_id,
                ),
            ),
        ),
    )


def _build_menus(
    prompts: Sequence[SystemPrompt],
    *,
    is_default_enabled: bool,
) -> None:
    for action_id in _action_ids:
        unregister_action(action_id)
    _action_ids.clear()

    default_toggle_action_id = (
        f'assistant:system-prompt:toggle:{DEFAULT_SYSTEM_PROMPT_ID}'
    )
    _action_ids.append(default_toggle_action_id)
    register_action(
        default_toggle_action_id,
        lambda: store.dispatch(
            AssistantToggleSystemPromptAction(prompt_id=DEFAULT_SYSTEM_PROMPT_ID),
        ),
        allow_reregister=True,
    )

    items = [
        MenuItemData(
            key=DEFAULT_SYSTEM_PROMPT_ID,
            label='Default',
            icon=CHECKED_ICON if is_default_enabled else UNCHECKED_ICON,
            background_color=SUCCESS_COLOR if is_default_enabled else None,
            action_id=default_toggle_action_id,
        ),
    ]

    for prompt in prompts:
        _register_detail_menu(prompt)
        open_action_id = f'assistant:system-prompt:open:{prompt.id}'
        _action_ids.append(open_action_id)
        register_action(
            open_action_id,
            lambda prompt_id=prompt.id: store.dispatch(
                StackPushMenuAction(
                    menu_key=f'{DETAIL_MENU_KEY_PREFIX}{prompt_id}',
                ),
            ),
            allow_reregister=True,
        )
        items.append(
            MenuItemData(
                key=f'prompt:{prompt.id}',
                label=prompt.label,
                icon=CHECKED_ICON if prompt.is_enabled else UNCHECKED_ICON,
                background_color=SUCCESS_COLOR if prompt.is_enabled else None,
                action_id=open_action_id,
            ),
        )

    items.append(
        MenuItemData(
            key='add',
            label='Add Prompt',
            icon='󰐕',
            action_id=_ADD_ACTION_ID,
        ),
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=MENU_ID,
            title='System Prompt',
            heading='System Prompt',
            sub_heading='Enable one or more prompts.',
            items=tuple(items),
        ),
    )


def setup_system_prompt_menu() -> None:
    """Register the static actions and the menu-building autorun."""
    register_action(
        _ADD_ACTION_ID,
        lambda: (create_task(_collect_prompt(None)), None)[1],
        allow_reregister=True,
    )
    register_action(
        _CANCEL_ACTION_ID,
        lambda: store.dispatch(MenuGoBackAction()),
        allow_reregister=True,
    )

    @store.autorun(
        lambda state: (
            state.assistant.system_prompts,
            state.assistant.is_default_system_prompt_enabled,
        ),
    )
    def system_prompt_menus(
        data: tuple[tuple[SystemPrompt, ...], bool],
    ) -> None:
        """Rebuild the system-prompt list and every per-prompt detail page."""
        prompts, is_default_enabled = data
        _build_menus(prompts, is_default_enabled=is_default_enabled)
