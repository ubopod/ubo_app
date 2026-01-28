# GUI Logic Migration Plan

## Goal
Decouple UI logic from the rendering layer so that building GUI clients on any platform (WearOS, Apple Watch, Web, etc.) becomes simple. Clients call gRPC API to get serializable ViewData and dispatch actions - all navigation and menu stack logic is handled by the backend.

## Architecture Overview

### Event-Driven UI Model

The core principle is that **UI subscribes to ViewChangedEvent** which is emitted when:
1. **User-initiated actions**: Button press, menu selection, scroll, etc.
2. **State changes**: Sensor updates, notifications, service status changes, etc.

Both trigger the same flow: Action -> Reducer -> State Update -> ViewChangedEvent -> UI Render

```
+---------------------------------------------------------------------+
|                         UBO DEVICE (BACKEND)                         |
+---------------------------------------------------------------------+
|                                                                      |
|  +--------------------------------------------------------------+   |
|  |                        Redux Store                            |   |
|  |                                                               |   |
|  |  +-------------+    +-------------+    +------------------+   |   |
|  |  | All State   |--->|   Reducer   |--->| ViewData (dumb)  |   |   |
|  |  | (stack,     |    | (computes   |    | (serializable)   |   |   |
|  |  | sensors,    |    | view from   |    |                  |   |   |
|  |  | audio, etc) |    | full state) |    | + StatusBarData  |   |   |
|  |  +-------------+    +-------------+    +------------------+   |   |
|  |         ^                                       |             |   |
|  |         |                                       v             |   |
|  |  +--------------------------------------------------------------+ |
|  |  |                     Actions                                  | |
|  |  |  * User actions: StackPushMenuAction, MenuScrollAction       | |
|  |  |  * State updates: SensorUpdateAction, VolumeChangeAction     | |
|  |  |  * Periodic: ClockTickAction, SystemMetricsAction            | |
|  |  +--------------------------------------------------------------+ |
|  |                                                               |   |
|  +--------------------------------------------------------------+   |
|                                        |                             |
|                                        v                             |
|                             +------------------+                     |
|                             | ViewChangedEvent |                     |
|                             | (broadcast to    |                     |
|                             |  all clients)    |                     |
|                             +------------------+                     |
|                                        |                             |
+----------------------------------------|-----------------------------+
|                    gRPC API            |                             |
|  +--------------+              +-------v--------+                    |
|  |DispatchAction|              | SubscribeEvent |                    |
|  |  (receive)   |              | (ViewChanged)  |                    |
|  +--------------+              +----------------+                    |
+---------------------------------------------------------------------+
          ^                                       |
          |                                       v
+---------------------------------------------------------------------+
|                      REMOTE CLIENTS (DUMB UI)                        |
+---------------------------------------------------------------------+
|  +------------+  +------------+  +------------+  +------------+     |
|  |  Web UI    |  |  WearOS    |  |Apple Watch |  |  Local     |     |
|  |  (React)   |  |  (Kotlin)  |  |  (Swift)   |  |  (Kivy)    |     |
|  +------------+  +------------+  +------------+  +------------+     |
|                                                                      |
|  Each client:                                                        |
|  1. Subscribes to ViewChangedEvent stream                            |
|  2. Renders ViewData (menus, status bar, notifications)              |
|  3. Dispatches actions on user interaction                           |
|  4. Uses separate streams for media (audio/video via existing gRPC)  |
+---------------------------------------------------------------------+
```

---

## Current State Analysis

### What's Done

**Phase 1: State Types** (Complete)
- `StackItemType` union: `MenuStackItem | ApplicationStackItem | NotificationStackItem`
- `ViewData` union: `HomeViewData | MenuViewData | ApplicationViewData | NotificationViewData`
- `MenuItemData`: Serializable menu item with `action_id` for click handling
- `StatusBarData`: Header/footer state (title, clock, icons, progress notifications)
- Stack actions: `StackPushMenuAction`, `StackPopAction`, `StackSetPageIndexAction`, etc.
- Events: `ViewChangedEvent`, `StackChangedEvent`

**Phase 2: Reducer Logic** (Complete)
- `compute_view_from_stack()`: Computes ViewData from Redux state
- Stack action handlers update state and emit `ViewChangedEvent`
- `derive_path_from_stack()`: Backward compatibility for legacy path

**Phase 2.5: Validation Bridge** (Complete)
- `MenuAppCentral._sync_redux_stack_with_gui()`: Syncs GUI->Redux for validation
- Debug logging with `DEBUG_MENU` flag
- `ViewRenderer` skeleton that subscribes to `ViewChangedEvent`

### What's Missing

1. **Autorun Migration** - Current autoruns directly update Kivy widgets; need to migrate to ViewChangedEvent
2. **Phase 3: Redux as Source of Truth** - GUI follows Redux (invert control flow)
3. **ViewRenderer Implementation** - Actually render ViewData to Kivy widgets
4. **StatusBarData Computation** - CPU%, RAM%, volume, icons, clock, temp, light
5. **gRPC Proto Definitions** - ViewData types not in proto files
6. **gRPC ViewChanged Subscription** - No dedicated stream for UI state
7. **Input Action Translation** - Remote clients need to dispatch actions
8. **Application View Serialization** - Apps need to provide ViewData
9. **Web UI Integration** - Subscribe to ViewChangedEvent instead of polling state
10. **Test Coverage** - Tests for view computation and rendering

---

## Autorun Migration Plan

### Key Principle: Autoruns Dispatch Actions, Not Return Widgets

Currently, many autoruns return ubo-gui types directly (like `HeadlessMenu`, `UboApplicationItem`). This tightly couples state changes to UI widgets.

**Current Pattern (to be migrated):**
```python
@store.autorun(lambda state: state.wifi.connections)
def wireless_connections_menu(connections: Sequence[WiFiConnection] | None) -> HeadlessMenu:
    # Returns a ubo-gui HeadlessMenu directly
    return HeadlessMenu(
        title='Wi-Fi',
        items=[UboApplicationItem(key=conn.ssid, ...) for conn in connections],
    )
```

**New Pattern:**
```python
@store.autorun(lambda state: state.wifi.connections)
def wireless_connections_menu(connections: Sequence[WiFiConnection] | None) -> None:
    # Compute serializable menu data
    items = [
        MenuItemData(
            key=conn.ssid,
            label=conn.ssid,
            icon=get_signal_icon(conn.signal_strength),
            action_id=f'wifi:open-connection:{conn.ssid}',
        )
        for conn in (connections or [])
    ]

    # Dispatch action to update store
    store.dispatch(UpdateDynamicMenuAction(
        menu_id='wifi:connections',
        title='Wi-Fi',
        items=items,
        placeholder='No Wi-Fi connections found' if connections else 'Loading...',
    ))
```

The store reducer handles `UpdateDynamicMenuAction`, updates the menu state, and emits `ViewChangedEvent`.

### Two Types of Autoruns

**Type 1: UI Widget Autoruns (MUST MIGRATE)**
These return or directly update ubo-gui widgets. They must be changed to dispatch actions.

**Type 2: State-to-Action Autoruns (KEEP)**
These already follow the pattern of dispatching actions based on state. These are fine.

### Current Autoruns Inventory

#### Category A: UI Widget Autoruns (MUST MIGRATE)

These directly return or update ubo-gui widgets. Must be changed to dispatch actions.

**menu_header.py (5 autoruns)**
| Autorun Selector | Current Behavior | Migration: Dispatch Action |
|------------------|------------------|----------------------------|
| `state.notifications.notifications` (with progress) | Creates SpinnerWidget/ProgressRingWidget | Already in state; ViewRenderer reads `StatusBarData.progress_notifications` |
| `state.main.is_header_visible` | Shows/hides header layout | Already in state; ViewRenderer reads `ViewData.show_status_bar` |
| `state.main.is_recording` | Shows blue recording indicator | Already in state; ViewRenderer reads `StatusBarData.is_recording` |
| `state.main.is_replaying` | Shows replay indicator | Already in state; ViewRenderer reads `StatusBarData.is_replaying` |
| `state.audio.is_recording` | Shows green recording indicator | Already in state; ViewRenderer reads `StatusBarData.is_recording_audio` |

**menu_footer.py (4 autoruns + 1 Kivy Clock)**
| Autorun Selector | Current Behavior | Migration: Dispatch Action |
|------------------|------------------|----------------------------|
| `state.sensors.temperature.value` | Updates temperature label | Already in state; ViewRenderer reads `StatusBarData.temperature` |
| `state.sensors.light.value` | Updates light icon opacity | Already in state; ViewRenderer reads `StatusBarData.light_level` |
| `state.status_icons.icons` | Renders icon labels | Already in state; ViewRenderer reads `StatusBarData.icons` |
| `state.main.is_footer_visible` | Shows/hides footer layout | Already in state; ViewRenderer reads `ViewData.show_status_bar` |
| Kivy `Clock.schedule_once` (every minute) | Updates clock text | Dispatch `SystemMetricsUpdateAction` with clock |

**home_page.py (1 autorun + 2 Kivy Clocks)**
| Autorun Selector | Current Behavior | Migration: Dispatch Action |
|------------------|------------------|----------------------------|
| `state.audio.playback_volume` | Updates VolumeWidget | Already in state; ViewRenderer reads `HomeViewData.volume_level` |
| Kivy `Clock.schedule_interval` (every 1s) | Updates CPU gauge via psutil | Dispatch `SystemMetricsUpdateAction` with cpu_percent |
| Kivy `Clock.schedule_interval` (every 1s) | Updates RAM gauge via psutil | Dispatch `SystemMetricsUpdateAction` with ram_percent |

#### Category B: Menu-Returning Autoruns (MUST MIGRATE)

These return `HeadlessMenu`, `SubMenuItem`, or `UboApplicationItem` directly. Must be changed to dispatch menu update actions.

**services/030-wifi/pages/main.py**
```python
@store.autorun(lambda state: state.wifi.connections)
def wireless_connections_menu(...) -> HeadlessMenu:  # Returns ubo-gui type
```
Migration: Dispatch `UpdateDynamicMenuAction(menu_id='wifi:connections', items=[...])`.

**Similar patterns exist in other services** - need to audit all services for menu-returning autoruns.

#### Category C: State-to-Action Autoruns (KEEP AS-IS)

These already dispatch actions. No migration needed.

**menu_central.py (1 autorun)**
| Autorun Selector | Current Behavior | Status |
|------------------|------------------|--------|
| `state.main.menu` | Sets root menu on MenuWidget | Keep for backward compat during migration |

**menu.py (2 autoruns)**
| Autorun Selector | Current Behavior | Status |
|------------------|------------------|--------|
| `state.settings.visual_debug` | Enables visual debug mode | Keep (debug feature) |
| `state.display.is_blanked` | Shows blank overlay | Keep (hardware control) |

### Migration Strategy

#### Step 1: Add Dynamic Menu State

Currently, menus are built by returning `HeadlessMenu` objects from autoruns. Instead, we need:

1. A state slice for dynamic menus:
```python
# In ubo_app/store/services/dynamic_menus/types.py
class DynamicMenuState(Immutable):
    menus: dict[str, DynamicMenuData] = field(default_factory=dict)

class DynamicMenuData(Immutable):
    menu_id: str
    title: str
    items: tuple[MenuItemData, ...]
    placeholder: str = ''
```

2. Actions to update dynamic menus:
```python
class UpdateDynamicMenuAction(BaseAction):
    menu_id: str  # e.g., 'wifi:connections'
    title: str
    items: tuple[MenuItemData, ...]
    placeholder: str = ''
```

#### Step 2: Migrate Menu-Returning Autoruns (Category B)

Change autoruns from returning widgets to dispatching actions:

**Before:**
```python
@store.autorun(lambda state: state.wifi.connections)
def wireless_connections_menu(connections) -> HeadlessMenu:
    return HeadlessMenu(title='Wi-Fi', items=[...])
```

**After:**
```python
@store.autorun(lambda state: state.wifi.connections)
def wireless_connections_menu(connections) -> None:
    items = tuple(
        MenuItemData(
            key=conn.ssid,
            label=conn.ssid,
            icon=get_signal_icon(conn.signal_strength),
            action_id=f'open:wifi:connection-page:{conn.ssid}',
        )
        for conn in (connections or [])
    )
    store.dispatch(UpdateDynamicMenuAction(
        menu_id='wifi:connections',
        title='Wi-Fi',
        items=items,
        placeholder='Loading...' if connections is None else 'No connections',
    ))
```

#### Step 3: Add Periodic State Updates

Create a service to dispatch periodic system metrics:

```python
# ubo_app/services/000-system-metrics/setup.py
async def init_service():
    async def update_metrics():
        while True:
            store.dispatch(SystemMetricsUpdateAction(
                cpu_percent=psutil.cpu_percent(percpu=False),
                ram_percent=psutil.virtual_memory().percent,
                clock=datetime.now().strftime('%H:%M'),
            ))
            await asyncio.sleep(1)

    create_task(update_metrics())
```

#### Step 4: Consolidate View Computation

The reducer computes ViewData from all relevant state slices:

```python
def compute_full_view(state: RootState) -> tuple[ViewData, StatusBarData]:
    # Navigation view from stack
    view = compute_navigation_view(state.main.stack, state.main.menu)

    # If current view references a dynamic menu, resolve it
    if isinstance(view, MenuViewData) and view.menu_id in state.dynamic_menus.menus:
        dynamic_menu = state.dynamic_menus.menus[view.menu_id]
        view = replace(view, title=dynamic_menu.title, items=dynamic_menu.items)

    # Status bar from multiple state slices
    status_bar = StatusBarData(
        title=state.main.title,
        is_recording=state.main.is_recording,
        is_replaying=state.main.is_replaying,
        is_recording_audio=state.audio.is_recording,
        progress_notifications=compute_progress_notifications(state.notifications),
        clock=state.system.clock,
        temperature=state.sensors.temperature.value,
        light_level=state.sensors.light.value,
        icons=tuple(StatusIconData(symbol=i.symbol, color=i.color)
                    for i in state.status_icons.icons),
    )

    # Enrich home view with system metrics
    if isinstance(view, HomeViewData):
        view = replace(view,
            cpu_percent=state.system.cpu_percent,
            ram_percent=state.system.ram_percent,
            volume_level=state.audio.playback_volume,
        )

    return view, status_bar
```

#### Step 5: Emit ViewChangedEvent on Relevant State Changes

Use a centralized view computation that emits `ViewChangedEvent` when any of these change:
- `state.main.stack`, `state.main.menu`, `state.main.is_recording`, `state.main.is_replaying`
- `state.audio.is_recording`, `state.audio.playback_volume`
- `state.notifications.notifications`
- `state.sensors.temperature`, `state.sensors.light`
- `state.status_icons.icons`
- `state.system.cpu_percent`, `state.system.ram_percent`, `state.system.clock`
- `state.dynamic_menus.menus`

**Implementation**: A top-level autorun that computes ViewData and dispatches ViewChangedEvent:

```python
@store.autorun(lambda state: (
    state.main.stack, state.main.menu, state.main.is_recording,
    state.audio.is_recording, state.notifications.notifications,
    state.sensors.temperature, state.status_icons.icons,
    state.system, state.dynamic_menus,
))
def emit_view_changed(state_tuple):
    view, status_bar = compute_full_view(store._state)
    # Only emit if changed (compare with previous)
    store.dispatch(ViewChangedInternalAction(view=view, status_bar=status_bar))
```

#### Step 6: Update UI Components to Use ViewRenderer

After ViewRenderer handles all rendering via ViewChangedEvent:
1. Remove widget-updating autoruns from `menu_header.py`, `menu_footer.py`, `home_page.py`
2. Remove Kivy Clock scheduling (replaced by periodic action dispatch)
3. UI components become pure renderers that listen to ViewChangedEvent

---

## Implementation Phases

### Phase 3A: Audit Menu-Returning Autoruns (COMPLETE)

**Total autoruns found: 55**

---

#### Category B: Menu-Returning Autoruns (20 - MUST MIGRATE)

These return `HeadlessMenu`, `HeadedMenu`, `Menu`, `list[Item]`, `list[SubMenuItem]`, etc.

| File | Function | Return Type | Priority |
|------|----------|-------------|----------|
| `store/update_manager/utils.py:354` | `about_menu_items` | `list[Item]` | Medium |
| `store/core/menus.py:90` | `notifications_menu_items` | `list[Item]` | High |
| `store/settings/services.py:111` | `error_items` | `list[Item]` | Medium |
| `store/settings/services.py:132` | `log_level_items` | `list[Item]` | Low |
| `store/settings/services.py:160` | `items` | menu items | Medium |
| `store/settings/services.py:320` | `service_items` | `list[SubMenuItem]` | Medium |
| `services/050-users/setup.py:192` | `users_menu` | `Menu` | Medium |
| `services/000-display/setup.py:131` | `timeout_options` | `Sequence[Item]` | Low |
| `services/050-vscode/setup.py:216` | `vscode_menu` | `HeadedMenu` | Medium |
| `services/010-speech-synthesis/setup.py:220` | `_menu_items` | `Sequence[ActionItem]` | Low |
| `services/010-speech-synthesis/setup.py:304` | `_speech_synthesis_menu` | `HeadlessMenu` | Medium |
| `services/030-ip/setup.py:32` | `get_ip_addresses` | `list[SubMenuItem]` | Medium |
| `services/050-lightdm/setup.py:119` | `lightdm_menu` | `Menu` | Medium |
| `services/040-camera/pages.py:15` | `camera_settings_menu` | `HeadedMenu` | Low |
| `services/080-docker/setup.py:203` | `setup_menu` | `HeadedMenu` | High |
| `services/080-docker/setup.py:524` | `registries_menu_items` | `Sequence[Item]` | Low |
| `services/050-ssh/setup.py:60` | `ssh_items` | `Sequence[Item]` | Medium |
| `services/050-rpi-connect/setup.py:82` | `actions` | `list[ActionItem]` | Medium |
| `services/030-wifi/pages/main.py:136` | `wireless_connections_menu` | `HeadlessMenu` | High |
| `services/090-file-system/file_application.py:311` | `items` | `list[Item]` | Low |

**Assistant service** (multiple autoruns in `services/090-assistant/setup.py`):
- Lines 300, 345, 387, 429, 471, 514, 564 - various menu items for STT, LLM, TTS, etc.

---

#### Category C: String/Icon/Title Returning Autoruns (13 - MIGRATION NEEDED)

These return strings for callable menu fields (icon, title, label, sub_heading).

| File | Function | Returns | Migration |
|------|----------|---------|-----------|
| `store/core/menus.py:82` | `_notifications_title` | `str` | Include in MenuItemData |
| `store/core/menus.py:118` | `_notifications_color` | `str` | Include in MenuItemData |
| `store/settings/menu.py:19` | `_pdb_debug_icon` | `str` | Include in MenuItemData |
| `store/settings/menu.py:24` | `_visual_debug_icon` | `str` | Include in MenuItemData |
| `store/settings/menu.py:29` | `_beta_versions_icon` | `str` | Include in MenuItemData |
| `store/settings/services.py:94` | `sub_heading` | `str` | Include in MenuData |
| `store/settings/services.py:154` | `log_level_title` | `str` | Include in MenuData |
| `services/010-speech-synthesis/setup.py:239` | `_menu_sub_heading` | `str` | Include in MenuData |
| `services/050-lightdm/setup.py:88` | `lightdm_icon` | `str` | Include in MenuItemData |
| `services/050-lightdm/setup.py:101` | `lightdm_title` | `str` | Include in MenuData |
| `services/050-ssh/setup.py:88` | `ssh_icon` | `str` | Include in MenuItemData |
| `services/050-ssh/setup.py:101` | `ssh_title` | `str` | Include in MenuData |
| `services/050-rpi-connect/setup.py:113` | `status` | `str` | Include in MenuData |

---

#### Category A: UI Widget Updating Autoruns (10 - REMOVE AFTER VIEWRENDERER)

These update Kivy widgets directly. Remove after ViewRenderer handles rendering.

| File | Line | Updates | Replacement |
|------|------|---------|-------------|
| `menu_app/menu_footer.py` | 53 | temperature label | `StatusBarData.temperature` |
| `menu_app/menu_footer.py` | 97 | light icon | `StatusBarData.light_level` |
| `menu_app/menu_footer.py` | 210 | status icons | `StatusBarData.icons` |
| `menu_app/menu_footer.py` | 215 | footer visibility | `ViewData.show_status_bar` |
| `menu_app/menu_header.py` | 196 | progress widgets | `StatusBarData.progress_notifications` |
| `menu_app/menu_header.py` | 205 | header visibility | `ViewData.show_status_bar` |
| `menu_app/menu_header.py` | 210 | recording indicator | `StatusBarData.is_recording` |
| `menu_app/menu_header.py` | 215 | replaying indicator | `StatusBarData.is_replaying` |
| `menu_app/menu_header.py` | 220 | audio recording | `StatusBarData.is_recording_audio` |
| `menu_app/home_page.py` | 44 | volume widget | `HomeViewData.volume_level` |

---

#### Category D: Internal/State-to-Action Autoruns (12 - KEEP AS-IS)

These dispatch actions, manage internal state, or control hardware. No migration needed.

| File | Line | Purpose |
|------|------|---------|
| `service_thread.py` | 308 | Set service log level |
| `utils/persistent_store.py` | 31 | Persist state to disk |
| `menu_app/menu.py` | 86 | Visual debug mode |
| `menu_app/menu.py` | 92 | Display blank state |
| `menu_app/menu_central.py` | 92 | Set root menu on MenuWidget |
| `menu_app/menu_central.py` | 103 | Stack sync validation (DEBUG) |
| `side_effects.py` | 188 | PDB debug mode signal |
| `rpc/store_service.py` | 202 | gRPC subscription queue |
| `services/000-audio/setup.py` | 116-124 | Hardware volume/mute control |
| `services/040-camera/setup.py` | 82 | Camera index selection |
| `services/090-infrared/setup.py` | 93, 113 | IR receiver control |
| `services/090-speech-recognition/*` | Various | Engine selection/state |

---

### Migration Summary

| Category | Count | Action Required |
|----------|-------|-----------------|
| B: Menu-returning | 20+ | Migrate to dispatch `UpdateDynamicMenuAction` |
| C: String-returning | 13 | Include computed values in MenuData/MenuItemData |
| A: Widget-updating | 10 | Remove after ViewRenderer implemented |
| D: Internal/Keep | 12 | No change |

**Total migration effort**: ~33 autoruns need changes

---

### Phase 3B: Create Dynamic Menu State Infrastructure
**Goal**: Add state and actions for dynamic menus

**Tasks**:
1. Create `DynamicMenuState` and `DynamicMenuData` types
2. Create `UpdateDynamicMenuAction` action
3. Add reducer for dynamic menu state
4. Integrate dynamic menus into view computation

**Files**:
- `ubo_app/store/services/dynamic_menus/types.py` - New state types
- `ubo_app/store/services/dynamic_menus/reducer.py` - Reducer
- `ubo_app/store/core/reducer.py` - Integrate into view computation

---

### Phase 3C: Complete StatusBarData Computation
**Goal**: StatusBarData should be fully computed in the reducer

**Tasks**:
1. Create `SystemMetricsState` for CPU, RAM, clock
2. Add periodic action dispatcher (system-metrics service)
3. Extend view computation to include status bar data
4. Emit ViewChangedEvent when any relevant state changes

**Files**:
- `ubo_app/store/services/system/types.py` - New SystemMetricsState
- `ubo_app/services/000-system-metrics/setup.py` - New periodic dispatcher
- `ubo_app/store/core/reducer.py` - Enhanced view computation

---

### Phase 4: Invert Control Flow (Redux -> GUI)
**Goal**: Redux becomes source of truth; GUI follows Redux state

**Tasks**:
1. **Implement ViewRenderer rendering methods**:
   - `_render_home_view()`: Set HomePage items, gauges
   - `_render_menu_view()`: Navigate to menu, set page index
   - `_render_application_view()`: Open application
   - `_render_notification_view()`: Display notification
   - `_render_status_bar()`: Update header/footer widgets

2. **Remove autoruns from UI components** (see migration table above)

3. **Input handling**:
   - Keypad/touch events dispatch Redux actions directly
   - Remove MenuWidget event handlers that modify GUI state

4. **Create render adapter for ubo-gui**:
   - Translate ViewData to MenuWidget method calls
   - Use MenuWidget as "dumb" renderer (no internal stack logic)

**Files**:
- `ubo_app/menu_app/view_renderer.py` - Implement rendering
- `ubo_app/menu_app/menu_central.py` - Remove sync, add action dispatching
- `ubo_app/menu_app/menu_header.py` - Remove autoruns
- `ubo_app/menu_app/menu_footer.py` - Remove autoruns
- `ubo_app/menu_app/home_page.py` - Remove autoruns and Kivy Clocks
- `ubo_app/services/000-keypad/setup.py` - Dispatch stack actions on button press

**Critical Considerations**:
- ubo-gui MenuWidget has its own stack - we either:
  a) Use it as dumb widget, manually set items/pages (preferred)
  b) Extend it to accept external stack control
  c) Fork/modify ubo-gui (avoid if possible)

---

### Phase 5: gRPC Proto Definitions for ViewData
**Goal**: All ViewData types serializable via protobuf

**Tasks**:
1. Add proto messages for:
   ```protobuf
   message MenuItemData {
     string key = 1;
     string label = 2;
     string icon = 3;
     string color = 4;
     bool is_short = 5;
     optional string action_id = 6;
     optional string background_color = 7;
   }

   message StatusIconData {
     string symbol = 1;
     repeated float color = 2;  // RGBA
   }

   message ProgressNotificationData {
     string id = 1;
     optional float progress = 2;
     repeated float color = 3;
   }

   message StatusBarData {
     string title = 1;
     bool is_recording = 2;
     bool is_replaying = 3;
     bool is_recording_audio = 4;
     repeated ProgressNotificationData progress_notifications = 5;
     string clock = 6;
     optional float temperature = 7;
     optional float light_level = 8;
     repeated StatusIconData icons = 9;
   }

   message HomeViewData {
     string type = 1;  // "home"
     bool show_status_bar = 2;
     repeated MenuItemData menu_items = 3;
     float cpu_percent = 4;
     float ram_percent = 5;
     float volume_level = 6;
   }

   message MenuViewData {
     string type = 1;  // "menu"
     bool show_status_bar = 2;
     string title = 3;
     repeated MenuItemData items = 4;
     int32 page_index = 5;
     int32 total_pages = 6;
   }

   message ApplicationViewData {
     string type = 1;  // "application"
     bool show_status_bar = 2;
     string application_id = 3;
     map<string, string> extra_data = 4;
   }

   message NotificationViewData {
     string type = 1;  // "notification"
     bool show_status_bar = 2;
     string notification_id = 3;
     string title = 4;
     string content = 5;
     string icon = 6;
     string color = 7;
   }

   message ViewData {
     oneof view {
       HomeViewData home_view = 1;
       MenuViewData menu_view = 2;
       ApplicationViewData application_view = 3;
       NotificationViewData notification_view = 4;
     }
   }

   message ViewChangedEvent {
     ViewData view = 1;
     optional StatusBarData status_bar = 2;
   }
   ```

2. Run `uv run poe proto` to regenerate

3. Update `object_to_message.py` to handle new types

**Files**:
- `ubo_app/rpc/proto/ubo/v1/ubo.proto` - Add ViewData messages
- `ubo_app/rpc/object_to_message.py` - Handle ViewData serialization

---

### Phase 6: gRPC UI Subscription Service
**Goal**: Remote clients can subscribe to ViewChangedEvent stream

**Tasks**:
1. ViewChangedEvent is already subscribable via `subscribe_event` gRPC method
2. Verify serialization works for ViewData types
3. Add convenience method for UI subscription with initial state:
   ```python
   async def subscribe_ui(self) -> AsyncIterator[ViewChangedEvent]:
       # Emit current view immediately, then stream changes
   ```

4. Document the gRPC API for external client developers

**Files**:
- `ubo_app/rpc/store_service.py` - Verify/enhance event subscription
- `ubo_app/rpc/README.md` - Document UI subscription API

---

### Phase 7: Action Dispatch for UI Interactions
**Goal**: Remote clients dispatch actions when user interacts with UI

**Action Mapping**:
| User Action | Redux Action |
|-------------|--------------|
| Select menu item | `StackPushMenuAction(menu_key=item.key)` or dispatch `action_id` |
| Go back | `StackPopAction(count=1)` |
| Go home | `StackPopToRootAction()` |
| Scroll up | `MenuScrollAction(direction=UP)` |
| Scroll down | `MenuScrollAction(direction=DOWN)` |
| Open app | `StackPushApplicationAction(application_id=...)` |
| Close notification | `StackPopItemAction(item_id=...)` |

**Tasks**:
1. Ensure all actions are in proto files
2. Verify `dispatch_action` gRPC method handles all stack actions
3. Add action_id resolution: when item has `action_id`, client dispatches that action

**Files**:
- `ubo_app/rpc/proto/ubo/v1/ubo.proto` - Ensure stack actions exist
- `ubo_app/rpc/store_service.py` - Verify dispatch handling

---

### Phase 8: Application View Serialization
**Goal**: Applications provide serializable ViewData for their views

**Tasks**:
1. Define `ApplicationViewProvider` protocol:
   ```python
   class ApplicationViewProvider(Protocol):
       def get_view_data(self) -> ApplicationViewData:
           """Return serializable view data for this application."""
           ...
   ```

2. Applications that can be serialized implement this protocol

3. Applications with media streams (camera, audio):
   - `ApplicationViewData.extra_data` contains stream info
   - `extra_data = {"video_stream": "grpc://...", "audio_stream": "grpc://..."}`
   - Client uses separate gRPC streams for media

4. Simple applications (text display, forms):
   - Fully serialize form fields, text content
   - Add form-specific ViewData types as needed

**Files**:
- `ubo_app/store/core/types.py` - ApplicationViewProvider protocol
- Various service applications - Implement protocol

---

### Phase 9: Web UI Integration
**Goal**: Web UI uses ViewChangedEvent instead of polling

**Tasks**:
1. Update web-app to subscribe to ViewChangedEvent via gRPC-web
2. Render ViewData in React components
3. Dispatch actions via gRPC when user interacts
4. Handle status bar updates

**Files**:
- `ubo_app/services/090-web-ui/web-app/src/` - React components for ViewData
- `ubo_app/services/090-web-ui/web-app/src/api/` - gRPC-web subscription

---

### Phase 10: Testing
**Goal**: Comprehensive test coverage for dumb UI architecture

**Tasks**:
1. Unit tests for `compute_view_from_stack()`:
   - Home view computation
   - Menu view with pagination
   - Application view
   - Notification view

2. Unit tests for stack action handlers:
   - Push/pop actions
   - Page index changes
   - ViewChangedEvent emission

3. Integration tests for gRPC:
   - Subscribe to ViewChangedEvent
   - Dispatch actions
   - Verify view updates

4. E2E tests:
   - Full navigation flow
   - Remote client simulation

**Files**:
- `tests/store/test_view_computation.py` - View computation tests
- `tests/store/test_stack_actions.py` - Stack action tests
- `tests/integration/test_grpc_ui.py` - gRPC integration tests

---

## Implementation Order (Recommended)

1. **Phase 3A**: Audit menu-returning autoruns (understand scope)
2. **Phase 3B**: Create dynamic menu state infrastructure (foundation)
3. **Phase 5**: Proto definitions (enables gRPC testing)
4. **Phase 3C**: StatusBarData computation + periodic metrics (complete the data model)
5. **Phase 6**: gRPC UI subscription (enables remote testing)
6. **Phase 7**: Action dispatch (enables interaction testing)
7. **Phase 4**: Invert control flow (main migration - convert autoruns to dispatch actions)
8. **Phase 8**: Application serialization (app-by-app)
9. **Phase 9**: Web UI integration (first real client)
10. **Phase 10**: Testing (throughout, but formalized at end)

### Key Migration Principle

**Autoruns stay, but their behavior changes:**
- ❌ OLD: `@store.autorun(...) -> HeadlessMenu` (returns widget)
- ✅ NEW: `@store.autorun(...) -> None` + `store.dispatch(UpdateDynamicMenuAction(...))` (dispatches action)

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| ubo-gui MenuWidget has internal stack | HIGH | Use widget as dumb renderer, don't rely on its stack |
| Breaking existing services | HIGH | Keep backward compat events, gradual migration |
| Complex application views | MEDIUM | Hybrid approach - simple apps serialize, complex use streams |
| gRPC-web compatibility | MEDIUM | Test with Envoy proxy, existing infrastructure |
| Performance (frequent view updates) | MEDIUM | Debounce ViewChangedEvent, batch updates |
| Kivy mainthread requirements | MEDIUM | ViewRenderer uses @mainthread decorator |

---

## Success Criteria

1. Remote client can subscribe to ViewChangedEvent and render UI
2. Remote client can dispatch actions and see UI update
3. Local Kivy UI works via ViewRenderer (not direct widget manipulation)
4. Status bar data (clock, CPU, RAM, icons) fully serializable
5. Applications provide serializable ViewData
6. Web UI uses gRPC subscription (not polling)
7. All menu-returning autoruns migrated to dispatch actions
8. All widget-updating autoruns removed (ViewRenderer handles rendering)
9. All tests pass with 80%+ coverage

---

## Summary: What Changes for Each Layer

### Services (e.g., wifi, docker, camera)
| Before | After |
|--------|-------|
| `@store.autorun(...) -> HeadlessMenu` | `@store.autorun(...) -> None` + dispatch `UpdateDynamicMenuAction` |
| Return `UboApplicationItem`, `SubMenuItem` | Dispatch actions with `MenuItemData` |
| Register apps with `register_application()` | Same, but apps implement `ApplicationViewProvider` protocol |

### UI Components (menu_header, menu_footer, home_page)
| Before | After |
|--------|-------|
| `@store.autorun(...)` updates Kivy widgets directly | Removed - ViewRenderer handles all updates |
| `Clock.schedule_interval()` for CPU/RAM/clock | Removed - system-metrics service dispatches periodic actions |
| Multiple autoruns per component | Single subscription to `ViewChangedEvent` in ViewRenderer |

### Store/Reducer
| Before | After |
|--------|-------|
| Stack actions emit `ViewChangedEvent` | All UI-relevant actions trigger view recomputation |
| ViewData computed only on stack changes | ViewData computed on any relevant state change |
| No dynamic menu state | `DynamicMenuState` holds computed menu items |

### Remote Clients (Web, WearOS, Watch)
| Before | After |
|--------|-------|
| Poll state or subscribe to multiple selectors | Subscribe to single `ViewChangedEvent` stream |
| Build UI from raw state | Render from ViewData (dumb UI) |
| No standardized input handling | Dispatch well-defined actions |

---

## Questions for Clarification

1. **ubo-gui modification**: Can we add a "dumb mode" to MenuWidget that accepts external stack control, or should we wrap it entirely?

2. **Clock updates**: Should clock be updated via periodic action dispatch, or computed on-demand in ViewData?

3. **Application registration**: Currently apps register with `RegisterRegularAppAction`. Should this also specify serialization capability?

4. **Notification rendering**: NotificationViewData only has id - should it include full notification content, or should client look it up?

5. **Centralized vs distributed view computation**: Should one reducer compute all ViewData, or should each state slice emit ViewChangedEvent?
