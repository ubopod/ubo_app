"""Core types package for the Redux store.

This package organizes the types into cohesive modules by concern.
All types are re-exported here for backward compatibility.
"""

from __future__ import annotations

# Actions
from ubo_app.store.core.types.actions import (
    ClearDynamicMenuAction,
    CloseApplicationAction,
    CloseInstructionAction,
    DeregisterRegularAppAction,
    DynamicMenuAction,
    ExecuteMenuActionAction,
    MainAction,
    MenuAction,
    MenuChooseByIconAction,
    MenuChooseByIndexAction,
    MenuChooseByLabelAction,
    MenuGoBackAction,
    MenuGoHomeAction,
    MenuScrollAction,
    OpenApplicationAction,
    PowerAction,
    PowerOffAction,
    RebootAction,
    RegisterAppAction,
    RegisterRegularAppAction,
    RegisterSettingAppAction,
    ReplayRecordedSequenceAction,
    ReportReplayingDoneAction,
    ScreenshotDataAction,
    SetAreEnclosuresVisibleAction,
    StackAction,
    StackPopAction,
    StackPopItemAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushInstructionAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackPushPromptAction,
    StackSetPageIndexAction,
    TakeScreenshotAction,
    ToggleRecordingAction,
    UpdateApplicationKwargsAction,
    UpdateCurrentViewAction,
    UpdateDynamicMenuAction,
    UpdateInstructionProgressAction,
    UpdateLightDMState,
    service_default_factory,
)

# Dynamic menus
from ubo_app.store.core.types.dynamic_menus import (
    DynamicMenuData,
    DynamicMenusState,
)

# Enums
from ubo_app.store.core.types.enums import (
    MenuScrollDirection,
    SettingsCategory,
)

# Events
from ubo_app.store.core.types.events import (
    DynamicMenuChangedEvent,
    ExecuteMenuActionEvent,
    InitEvent,
    MainEvent,
    MenuChooseByIconEvent,
    MenuChooseByIndexEvent,
    MenuChooseByLabelEvent,
    MenuEvent,
    PowerEvent,
    PowerOffEvent,
    RebootEvent,
    ReplayRecordedSequenceEvent,
    ScreenshotDataEvent,
    ScreenshotEvent,
    SnapshotEvent,
    StackChangedEvent,
    StackPageIndexChangedEvent,
    StoreRecordedSequenceEvent,
    ViewChangedEvent,
)

# Stack items
from ubo_app.store.core.types.stack_items import (
    ApplicationStackItem,
    InstructionStackItem,
    MenuStackItem,
    NotificationStackItem,
    PromptStackItem,
    StackItemType,
)

# State
from ubo_app.store.core.types.state import MainState, RegisteredAppEntry

# Status bar
from ubo_app.store.core.types.status_bar import (
    ProgressNotificationData,
    StatusBarData,
    StatusIconData,
)

# View data
from ubo_app.store.core.types.view_data import (
    ApplicationViewData,
    HomeViewData,
    InstructionViewData,
    MenuItemData,
    MenuViewData,
    NotificationViewData,
    PromptViewData,
    ViewData,
)

__all__ = [
    'ApplicationStackItem',
    'ApplicationViewData',
    'ClearDynamicMenuAction',
    'CloseApplicationAction',
    'CloseInstructionAction',
    'DeregisterRegularAppAction',
    'DynamicMenuAction',
    'DynamicMenuChangedEvent',
    'DynamicMenuData',
    'DynamicMenusState',
    'ExecuteMenuActionAction',
    'ExecuteMenuActionEvent',
    'HomeViewData',
    'InitEvent',
    'InstructionStackItem',
    'InstructionViewData',
    'MainAction',
    'MainEvent',
    'MainState',
    'MenuAction',
    'MenuChooseByIconAction',
    'MenuChooseByIconEvent',
    'MenuChooseByIndexAction',
    'MenuChooseByIndexEvent',
    'MenuChooseByLabelAction',
    'MenuChooseByLabelEvent',
    'MenuEvent',
    'MenuGoBackAction',
    'MenuGoHomeAction',
    'MenuItemData',
    'MenuScrollAction',
    'MenuScrollDirection',
    'MenuStackItem',
    'MenuViewData',
    'NotificationStackItem',
    'NotificationViewData',
    'OpenApplicationAction',
    'PowerAction',
    'PowerEvent',
    'PowerOffAction',
    'PowerOffEvent',
    'ProgressNotificationData',
    'PromptStackItem',
    'PromptViewData',
    'RebootAction',
    'RebootEvent',
    'RegisterAppAction',
    'RegisterRegularAppAction',
    'RegisterSettingAppAction',
    'RegisteredAppEntry',
    'ReplayRecordedSequenceAction',
    'ReplayRecordedSequenceEvent',
    'ReportReplayingDoneAction',
    'ScreenshotDataAction',
    'ScreenshotDataEvent',
    'ScreenshotEvent',
    'SetAreEnclosuresVisibleAction',
    'SettingsCategory',
    'SnapshotEvent',
    'StackAction',
    'StackChangedEvent',
    'StackItemType',
    'StackPageIndexChangedEvent',
    'StackPopAction',
    'StackPopItemAction',
    'StackPopToRootAction',
    'StackPushApplicationAction',
    'StackPushInstructionAction',
    'StackPushMenuAction',
    'StackPushNotificationAction',
    'StackPushPromptAction',
    'StackSetPageIndexAction',
    'StatusBarData',
    'StatusIconData',
    'StoreRecordedSequenceEvent',
    'TakeScreenshotAction',
    'ToggleRecordingAction',
    'UpdateApplicationKwargsAction',
    'UpdateCurrentViewAction',
    'UpdateDynamicMenuAction',
    'UpdateInstructionProgressAction',
    'UpdateLightDMState',
    'ViewChangedEvent',
    'ViewData',
    'service_default_factory',
]
