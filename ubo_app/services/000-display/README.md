# Display Service (`000-display`)

## Overview

The display service owns the screen's power/activity state: it tracks user activity, blanks the
screen after a configurable inactivity timeout, wakes it on the next interaction, and exposes the
pause/resume/redraw signals the rendering pipeline listens to. It does **not** push pixels itself
(that is `ubo_app/display.py` and `ubo_app/menu_app/menu.py`); it is the state authority that tells
those consumers *when* to blank, unblank, or redraw.

It loads in the `000-` (core hardware) tier because the screen is fundamental output that many later
services render into — the display slice must exist before anything can draw. See
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the store/render contract.

## Files

| Path            | Purpose                                                                         |
| --------------- | ------------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration; wires the reducer and calls `init_service()`.                     |
| `setup.py`      | Runtime: inactivity monitor, timeout dynamic menu, event subscriptions, matcher.|
| `reducer.py`    | Pure reducer for the `display` slice; maps actions → state + blank/redraw events.|

Store types: [`ubo_app/store/services/display.py`](../../store/services/display.py).

## State

Slice: `state.display` — [`DisplayState`](../../store/services/display.py):

| Field                    | Type                          | Meaning                                                        |
| ------------------------ | ----------------------------- | ------------------------------------------------------------- |
| `is_paused`              | `bool`                        | Rendering is suspended (`DisplayPauseAction`).                |
| `is_blanked`             | `bool`                        | Screen is currently blanked for inactivity.                  |
| `last_activity_time`     | `float \| None`               | UTC timestamp of the last user activity; drives the timeout. |
| `selected_blank_timeout` | `DisplayBlankTimeout`         | Persisted timeout choice (default `TEN_MINUTES`; `OFF` disables blanking). |

`DisplayBlankTimeout` is a `StrEnum` of `1/5/10/30 minute`, `1 hour`, and `OFF`; each member exposes
`get_timeout_seconds()` (`None` for `OFF`) and `get_label()`.

## Actions & Events

Per the store contract, **events are emitted only from the reducer**; `setup.py` subscribes to them
for side effects.

| Action                        | Reducer result                                                          |
| ----------------------------- | ----------------------------------------------------------------------- |
| `DisplayPauseAction`          | `is_paused = True`.                                                      |
| `DisplayResumeAction`         | `is_paused = False`; → `DisplayRedrawEvent`.                             |
| `DisplayRedrawAction`         | → `DisplayRedrawEvent` (state unchanged).                               |
| `DisplayBlankAction`          | `is_blanked = True`; → `DisplayBlankEvent`.                             |
| `DisplayUnblankAction`        | `is_blanked = False`, stamps `last_activity_time`; → `DisplayUnblankEvent` + `DisplayRedrawEvent`. |
| `DisplayUpdateActivityAction` | Stamps `last_activity_time` (keeps the screen awake).                    |
| `DisplaySetBlankTimeoutAction`| Stores `selected_blank_timeout`.                                        |
| `AssistantStart/Stop/ToggleListeningAction` | Cross-service: updates activity, and if blanked wakes the screen (→ `DisplayUnblankEvent` + `DisplayRedrawEvent`). |

`DisplayRenderEvent` / `DisplayCompressedRenderEvent` also live in the slice — they carry framebuffer
data emitted by the render layer, not the reducer here.

> `DisplayUnblankAction.timestamp` / `DisplayUpdateActivityAction.timestamp` default to
> `default_now()` (the monkey-patchable clock in `ubo_app/utils/clock.py`) so the reducer stays pure
> and deterministic under tests.

## Runtime & Setup

`init_service()` (`setup.py:173`) registers the Settings entry, the timeout path matcher, and the
persistent store, seeds activity, subscribes to the blank/unblank events, and (outside tests) starts
the inactivity monitor:

```python
store.subscribe_event(DisplayBlankEvent, handle_blank_event)
store.subscribe_event(DisplayUnblankEvent, handle_unblank_event)

if not IS_TEST_ENV:
    create_task(monitor_inactivity())
```

Reactive/loop pieces:

- `monitor_inactivity()` (`setup.py:44`) — a long-lived loop that reads the slice via
  `store.with_state`, and once `last_activity_time` is older than `selected_blank_timeout`, dispatches
  `DisplayBlankAction`. When already blanked it **waits on `_unblank_event`** instead of polling; the
  `DisplayUnblankEvent` handler sets that event to wake the loop. `OFF` timeout skips blanking. The
  monitor is **not started under `IS_TEST_ENV`** so screenshots aren't blanked mid-test.
- `update_display_dynamic_menu` (`setup.py:151`) — `@store.autorun` on `selected_blank_timeout`;
  rebuilds the timeout selection menu (via `build_selection_menu`) and lazily registers the per-option
  action handlers on first run.

`init_service()` returns `[unregister_settings]` for teardown.

## User Interface

- **Settings entry:** `RegisterSettingAppAction` under `SettingsCategory.HARDWARE` ("Display").
- **Dynamic menu (dumb UI):** `DISPLAY_TIMEOUT_MENU_ID = 'display:timeout'`, a `build_selection_menu`
  of the six timeout options; the selected option is checkmarked.
- **Action handlers:** `display:set_timeout:<value>` per `DisplayBlankTimeout` member (registered with
  `allow_reregister=True`).
- **Path matcher:** `display:settings` resolves `('main', 'settings', <category>, 'display:')` to the
  timeout menu.

## Cross-Service Interactions

- **Reacts to the assistant:** listening start/stop/toggle actions update activity and wake a blanked
  screen, so invoking the assistant lights the display.
- **Driven by the keypad:** `000-keypad` dispatches `DisplayUnblankAction` / `DisplayUpdateActivityAction`
  on key presses (the keypad also mirrors `display.is_blanked` into its own slice).
- **Consumed by the render layer:** `ubo_app/display.py` and `ubo_app/menu_app/menu.py` act on the
  blank/unblank/redraw events.

## Configuration

No env vars or secrets. Constants: `DISPLAY_TIMEOUT_MENU_ID = 'display:timeout'`; persistent key
`display:selected_blank_timeout` (default `TEN_MINUTES`).

## Testing & Development Notes

Related tests:

| Test                                        | Tier        | What it covers                                                      |
| ------------------------------------------- | ----------- | ------------------------------------------------------------------ |
| `tests/integration/test_services.py`        | Integration | Asserts the `display` service registers and the store snapshot matches. |
| `tests/navigation/test_keypad_reducer.py`   | Unit        | Indirectly exercises the wake path: a keypress on a blanked screen emits `DisplayUnblankAction`. |

> There is currently **no dedicated unit test** for the display reducer. It is pure and cheap to
> cover (feed `DisplayBlankAction`/`DisplayUnblankAction`/`DisplaySetBlankTimeoutAction`, assert the
> resulting `DisplayState` and emitted events); adding `tests/store/test_display_reducer.py` is a
> good first contribution.

**Maintenance when you change this service:**

- **State shape** (`DisplayState`) or the timeout menu output → regenerate store/window snapshots
  (via the Docker `--override-store-snapshots`/`--override-window-snapshots` flow); never hand-edit
  snapshot files.
- **Reducer branch** (new action/event) → add a small pure-reducer test in
  `tests/store/test_display_reducer.py` rather than an E2E flow.
- **Input/timeout options** → the selection-menu output feeds snapshots; regenerate them.
- The inactivity monitor is disabled under `IS_TEST_ENV`, so blanking-after-timeout behavior is only
  observable on-device or by driving `read_metrics`/`monitor_inactivity` manually.

To exercise manually: Settings → Hardware → Display to change the timeout, then leave the device idle
and confirm it blanks and that any keypress or assistant trigger wakes it.
