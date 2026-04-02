"""Tests for instruction and prompt stack item types.

These test the new InstructionViewData and PromptViewData view types
which generalize the registration/confirmation page patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.store.core.types import (
    ApplicationViewData,
    CloseInstructionAction,
    HomeViewData,
    InstructionStackItem,
    InstructionViewData,
    MenuItemData,
    MenuViewData,
    NotificationViewData,
    PromptViewData,
    StackPopAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushInstructionAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackPushPromptAction,
    UpdateInstructionProgressAction,
)

if TYPE_CHECKING:
    from tests.navigation.conftest import ReducerRunner


class TestInstructionView:
    """Tests for instruction/waiting view."""

    def test_push_instruction_shows_instruction_view(
        self,
        nav: ReducerRunner,
    ) -> None:
        """Pushing an instruction shows InstructionViewData."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(
            StackPushInstructionAction(
                title='Registering Device',
                instruction='Point remote and press 5 times',
                spinner=True,
                timeout_seconds=60,
                footer_text='Press BACK to cancel',
            ),
        )
        assert isinstance(nav.view, InstructionViewData)
        assert nav.view.title == 'Registering Device'
        assert nav.view.instruction == 'Point remote and press 5 times'
        assert nav.view.spinner is True
        assert nav.view.timeout_seconds == 60
        assert nav.view.footer_text == 'Press BACK to cancel'

    def test_pop_instruction_reveals_menu(self, nav: ReducerRunner) -> None:
        """Popping an instruction reveals the underlying menu."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushInstructionAction(title='Test'))
        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, MenuViewData)

    def test_instruction_does_not_change_path(
        self,
        nav: ReducerRunner,
    ) -> None:
        """Instructions don't alter the menu path (like applications)."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        path_before = nav.state.path
        nav.dispatch(StackPushInstructionAction(title='Test'))
        assert nav.state.path == path_before

    def test_instruction_stack_depth(self, nav: ReducerRunner) -> None:
        """InstructionViewData includes correct stack_depth."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushInstructionAction(title='Test'))
        assert isinstance(nav.view, InstructionViewData)
        assert nav.view.stack_depth == len(nav.state.stack)

    def test_close_instruction_by_id(self, nav: ReducerRunner) -> None:
        """CloseInstructionAction removes the instruction from the stack."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushInstructionAction(title='Test'))
        instruction_id = nav.state.stack[-1].id
        nav.dispatch(CloseInstructionAction(instruction_id=instruction_id))
        assert isinstance(nav.view, MenuViewData)

    def test_update_instruction_progress(self, nav: ReducerRunner) -> None:
        """UpdateInstructionProgressAction updates the progress_text."""
        nav.dispatch(StackPushInstructionAction(title='Test'))
        instruction_id = nav.state.stack[-1].id
        nav.dispatch(
            UpdateInstructionProgressAction(
                instruction_id=instruction_id,
                progress_text='Time remaining: 30s',
            ),
        )
        top = nav.state.stack[-1]
        assert isinstance(top, InstructionStackItem)
        assert top.progress_text == 'Time remaining: 30s'


class TestPromptView:
    """Tests for prompt/confirmation view."""

    def test_push_prompt_shows_prompt_view(self, nav: ReducerRunner) -> None:
        """Pushing a prompt shows PromptViewData."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(
            StackPushPromptAction(
                title='Remove Key',
                prompt='Remove "number1"?',
                icon='󰆴',
                items=(
                    MenuItemData(
                        key='yes',
                        label='Yes',
                        icon='󰆴',
                        action_id='test:yes',
                    ),
                    MenuItemData(
                        key='cancel',
                        label='Cancel',
                        icon='󰜺',
                        action_id='test:cancel',
                    ),
                ),
            ),
        )
        assert isinstance(nav.view, PromptViewData)
        assert nav.view.prompt == 'Remove "number1"?'
        assert len(nav.view.items) == 2
        assert nav.view.items[0].label == 'Yes'
        assert nav.view.items[1].label == 'Cancel'

    def test_pop_prompt_reveals_menu(self, nav: ReducerRunner) -> None:
        """Popping a prompt reveals the underlying menu."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushPromptAction(title='Test', prompt='Sure?'))
        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, MenuViewData)

    def test_prompt_does_not_change_path(self, nav: ReducerRunner) -> None:
        """Prompts don't alter the menu path."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        path_before = nav.state.path
        nav.dispatch(StackPushPromptAction(title='Test', prompt='Sure?'))
        assert nav.state.path == path_before

    def test_prompt_stack_depth(self, nav: ReducerRunner) -> None:
        """PromptViewData includes correct stack_depth."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushPromptAction(title='Test', prompt='Sure?'))
        assert isinstance(nav.view, PromptViewData)
        assert nav.view.stack_depth == len(nav.state.stack)

    def test_pop_to_root_clears_prompt(self, nav: ReducerRunner) -> None:
        """StackPopToRootAction clears prompts from the stack."""
        nav.dispatch(StackPushMenuAction(menu_key='main'))
        nav.dispatch(StackPushPromptAction(title='Test', prompt='Sure?'))
        nav.dispatch(StackPopToRootAction())
        assert isinstance(nav.view, HomeViewData)


class TestMixedInstructionPromptStack:
    """Tests for instructions/prompts interleaved with other stack items."""

    def test_notification_over_instruction(self, nav: ReducerRunner) -> None:
        """Notification pushed over instruction shows notification."""
        nav.dispatch(StackPushInstructionAction(title='Test'))
        nav.dispatch(StackPushNotificationAction(notification_id='n1'))
        assert isinstance(nav.view, NotificationViewData)

    def test_pop_notification_reveals_instruction(
        self,
        nav: ReducerRunner,
    ) -> None:
        """Popping notification reveals instruction underneath."""
        nav.dispatch(StackPushInstructionAction(title='Test'))
        nav.dispatch(StackPushNotificationAction(notification_id='n1'))
        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, InstructionViewData)

    def test_prompt_over_app(self, nav: ReducerRunner) -> None:
        """Prompt can be pushed over an application."""
        nav.dispatch(
            StackPushApplicationAction(application_id='test:app'),
        )
        nav.dispatch(
            StackPushPromptAction(title='Confirm', prompt='Sure?'),
        )
        assert isinstance(nav.view, PromptViewData)
        nav.dispatch(StackPopAction())
        assert isinstance(nav.view, ApplicationViewData)
