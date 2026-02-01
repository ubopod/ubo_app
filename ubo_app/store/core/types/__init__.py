"""Core types package for the Redux store.

This package organizes the types into cohesive modules by concern.
All types are re-exported here for backward compatibility.
"""

from __future__ import annotations

# Actions
from ubo_app.store.core.types.actions import (
    ClearDynamicMenuAction,
    CloseApplicationAction,
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
    SetAreEnclosuresVisibleAction,
    SetMenuPathAction,
    StackAction,
    StackPopAction,
    StackPopItemAction,
    StackPopToRootAction,
    StackPushApplicationAction,
    StackPushMenuAction,
    StackPushNotificationAction,
    StackSetPageIndexAction,
    ToggleRecordingAction,
    UpdateCurrentViewAction,
    UpdateDynamicMenuAction,
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
    CloseApplicationEvent,
    DynamicMenuChangedEvent,
    InitEvent,
    MainEvent,
    MenuChooseByIconEvent,
    MenuChooseByIndexEvent,
    MenuChooseByLabelEvent,
    MenuEvent,
    MenuGoBackEvent,
    MenuGoHomeEvent,
    MenuScrollEvent,
    OpenApplicationEvent,
    PowerEvent,
    PowerOffEvent,
    RebootEvent,
    ReplayRecordedSequenceEvent,
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
    MenuStackItem,
    NotificationStackItem,
    StackItemType,
)

# State
from ubo_app.store.core.types.state import MainState

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
    MenuItemData,
    MenuViewData,
    NotificationViewData,
    ViewData,
)

__all__ = [
    # Stack items
    'ApplicationStackItem',
    # View data
    'ApplicationViewData',
    # Actions
    'ClearDynamicMenuAction',
    'CloseApplicationAction',
    # Events
    'CloseApplicationEvent',
    'DeregisterRegularAppAction',
    'DynamicMenuAction',
    'DynamicMenuChangedEvent',
    # Dynamic menus
    'DynamicMenuData',
    'DynamicMenusState',
    'ExecuteMenuActionAction',
    'HomeViewData',
    'InitEvent',
    'MainAction',
    'MainEvent',
    # State
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
    'MenuGoBackEvent',
    'MenuGoHomeAction',
    'MenuGoHomeEvent',
    'MenuItemData',
    'MenuScrollAction',
    # Enums
    'MenuScrollDirection',
    'MenuScrollEvent',
    'MenuStackItem',
    'MenuViewData',
    'NotificationStackItem',
    'NotificationViewData',
    'OpenApplicationAction',
    'OpenApplicationEvent',
    'PowerAction',
    'PowerEvent',
    'PowerOffAction',
    'PowerOffEvent',
    # Status bar
    'ProgressNotificationData',
    'RebootAction',
    'RebootEvent',
    'RegisterAppAction',
    'RegisterRegularAppAction',
    'RegisterSettingAppAction',
    'ReplayRecordedSequenceAction',
    'ReplayRecordedSequenceEvent',
    'ReportReplayingDoneAction',
    'ScreenshotEvent',
    'SetAreEnclosuresVisibleAction',
    'SetMenuPathAction',
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
    'StackPushMenuAction',
    'StackPushNotificationAction',
    'StackSetPageIndexAction',
    'StatusBarData',
    'StatusIconData',
    'StoreRecordedSequenceEvent',
    'ToggleRecordingAction',
    'UpdateCurrentViewAction',
    'UpdateDynamicMenuAction',
    'UpdateLightDMState',
    'ViewChangedEvent',
    'ViewData',
    'service_default_factory',
]
