"""Production ViewData and status-bar contract tests."""

from __future__ import annotations

import math
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ubo_app.store.core import view_computation
from ubo_app.store.core.stack_ops import create_root_stack_item
from ubo_app.store.core.types import (
    ApplicationStackItem,
    ApplicationViewData,
    ChatStackItem,
    ChatViewData,
    DynamicMenusState,
    HomeViewData,
    InstructionStackItem,
    InstructionViewData,
    MainState,
    NotificationStackItem,
    NotificationViewData,
    PromptStackItem,
    PromptViewData,
    RenderStackItem,
    RenderViewData,
)
from ubo_app.store.core.view_computation import (
    compute_status_bar_data,
    compute_view_from_root_state,
    get_notification_view_data,
)
from ubo_app.store.services.chat import (
    ChatMessage,
    ChatMessageKind,
    ChatRole,
    ChatState,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationsState,
)
from ubo_app.store.services.sensors import SensorsState, SensorState

if TYPE_CHECKING:
    from ubo_app.store.core.types import StackItemType
    from ubo_app.store.main import RootState


@pytest.fixture(autouse=True)
def _stub_menus_module() -> object:
    """Avoid importing the side-effectful menus module in pure view tests."""
    module_key = 'ubo_app.store.core.menus'
    if module_key in sys.modules:
        yield
        return
    stub = ModuleType(module_key)
    stub.HOME_MENU_ID = 'home:main'  # type: ignore[attr-defined]
    sys.modules[module_key] = stub
    try:
        yield
    finally:
        del sys.modules[module_key]


def _root(main: MainState, **slices: object) -> RootState:
    """Build the minimal full-state shape used by view computation."""
    return cast(
        'RootState',
        SimpleNamespace(
            main=main,
            dynamic_menus=DynamicMenusState(),
            **slices,
        ),
    )


@pytest.mark.parametrize(
    ('stack_item', 'expected_type'),
    [
        (
            ApplicationStackItem(
                id='application',
                application_id='test:application',
                initialization_kwargs={'value': 1},
            ),
            ApplicationViewData,
        ),
        (
            RenderStackItem(
                id='render',
                kind='text',
                title='Details',
                props={'content': 'Hello'},
                stream_id='stream-1',
            ),
            RenderViewData,
        ),
        (
            InstructionStackItem(
                id='instruction',
                title='Wait',
                instruction='Processing',
                spinner=True,
            ),
            InstructionViewData,
        ),
        (
            PromptStackItem(
                id='prompt',
                title='Confirm',
                prompt='Continue?',
            ),
            PromptViewData,
        ),
    ],
)
def test_compute_view_from_root_state_preserves_stack_view_contract(
    stack_item: StackItemType,
    expected_type: type[object],
) -> None:
    """Every non-menu stack item becomes its matching serializable view."""
    main = MainState(stack=(*create_root_stack_item(), stack_item))

    view = compute_view_from_root_state(_root(main))

    assert isinstance(view, expected_type)
    assert isinstance(
        view,
        ApplicationViewData | RenderViewData | InstructionViewData | PromptViewData,
    )
    assert view.stack_depth == 2


def test_background_notification_does_not_steal_visible_view() -> None:
    """BACKGROUND notifications stay on the stack but leave the app visible."""
    background = Notification(
        id='background',
        title='Background',
        content='Progress only',
        display_type=view_computation.NotificationDisplayType.BACKGROUND,
    )
    application = ApplicationStackItem(id='application', application_id='test:app')
    main = MainState(
        stack=(
            *create_root_stack_item(),
            application,
            NotificationStackItem(id='notification', notification_id=background.id),
        ),
    )

    view = compute_view_from_root_state(
        _root(
            main,
            notifications=NotificationsState(
                notifications=(background,),
                unread_count=1,
            ),
        ),
    )

    assert isinstance(view, ApplicationViewData)
    assert view.application_id == application.application_id


def test_chat_view_styles_messages_and_clamps_scroll_offset() -> None:
    """Chat ViewData owns message styling and a bounded scroll offset."""
    messages = (
        ChatMessage(
            id='assistant',
            role=ChatRole.ASSISTANT,
            text='Hello',
            is_playing=True,
        ),
        ChatMessage(
            id='user',
            role=ChatRole.USER,
            kind=ChatMessageKind.AUDIO,
            text='Hi',
            waveform=(0.2, 0.8),
        ),
    )
    main = MainState(
        stack=(
            *create_root_stack_item(),
            ChatStackItem(id='chat', session_id='session', scroll_offset=99),
        ),
    )

    view = compute_view_from_root_state(
        _root(main, chat=ChatState(messages=messages, messages_revision=2)),
    )

    assert isinstance(view, ChatViewData)
    assert view.scroll_offset == 1
    assert view.total_bubbles == 2
    assert view.bubbles[0].alignment == 'left'
    assert view.bubbles[0].is_playing is True
    assert view.bubbles[1].alignment == 'right'
    assert view.bubbles[1].kind == 'audio'
    assert view.bubbles[1].waveform == (0.2, 0.8)


def test_missing_notification_reveals_underlying_view_and_has_safe_fallback() -> None:
    """A cleared notification cannot own the root view or crash direct rendering."""
    main = MainState(
        stack=(
            *create_root_stack_item(),
            NotificationStackItem(id='missing', notification_id='missing'),
        ),
    )

    view = compute_view_from_root_state(
        _root(main, notifications=NotificationsState(notifications=(), unread_count=0)),
    )

    assert isinstance(view, HomeViewData)

    fallback = get_notification_view_data(_root(main), 'missing')
    assert isinstance(fallback, NotificationViewData)
    assert fallback.notification_id == 'missing'
    assert fallback.title == ''


def test_compute_status_bar_data_collects_ui_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Progress, icons, metrics, and recording state reach the renderer."""
    monkeypatch.setattr(
        'ubo_app.store.core.view_computation.socket.gethostname',
        lambda: 'ubo-test',
    )
    progress = Notification(
        id='spinner',
        title='Spinner',
        content='',
        progress=math.nan,
    )
    measured = Notification(id='progress', title='Progress', content='', progress=0.25)
    state = _root(
        MainState(is_recording=True, is_replaying=True),
        notifications=NotificationsState(
            notifications=(progress, measured),
            unread_count=2,
        ),
        status_icons=SimpleNamespace(
            icons=(SimpleNamespace(symbol='wifi', color='blue'),),
        ),
        sensors=SensorsState(
            temperature=SensorState(value=21.5),
            light=SensorState(value=0.7),
        ),
        system=SimpleNamespace(clock='12:34'),
        audio=SimpleNamespace(is_recording=True),
    )

    status = compute_status_bar_data(state)

    assert status.title == '󰋜ubo-test.local'
    assert status.is_recording is True
    assert status.is_replaying is True
    assert status.is_recording_audio is True
    assert status.clock == '12:34'
    assert status.temperature == 21.5
    assert status.light_level == 0.7
    assert status.icons[0].symbol == 'wifi'
    assert [(item.id, item.progress) for item in status.progress_notifications] == [
        ('spinner', None),
        ('progress', 0.25),
    ]


def test_compute_status_bar_ignores_malformed_icon_source() -> None:
    """A malformed status-icon provider cannot break a view update."""
    status = compute_status_bar_data(
        _root(
            MainState(),
            status_icons=SimpleNamespace(icons=object()),
        ),
    )

    assert status.icons == ()
