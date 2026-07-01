# Notifications Service (`010-notifications`)

## Overview

The Notifications service is the device's central notification store and dispatcher: any service can
raise a `Notification` (transient FLASH, persistent STICKY, or silent BACKGROUND) and this service
holds it, tracks the unread count and aggregate progress, drives the RGB ring blink and chime that
accompany it, and keeps the notification overlays reconciled with the navigation stack. It also owns
the *action handlers* behind each notification's buttons (dismiss / custom actions / "extra info"
readout).

It loads in the `010-` tier (after core hardware, before higher-level features) because almost every
later service surfaces state to the user through a notification.

> **No `setup.py`.** Unlike most services, all runtime wiring lives directly in
> [`ubo_handle.py`](ubo_handle.py) — its `setup()` registers the reducer *and* subscribes the
> display/clear event handlers that register/unregister per-notification action handlers. There is no
> `init_service()`; there is nothing hardware- or autorun-shaped to justify a separate module.

## Files

| Path            | Purpose                                                                          |
| --------------- | ------------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration + the entire runtime: reducer wiring and notification action-handler (dis/re)registration on display/clear. |
| `reducer.py`    | Pure reducer for the `notifications` slice; maps actions → state/events/child-actions. |

Store types: [`ubo_app/store/services/notifications.py`](../../store/services/notifications.py). For
the action→reducer→event→subscriber model, see
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## State

Slice: `state.notifications` — [`NotificationsState`](../../store/services/notifications.py):

| Field           | Type                     | Meaning                                                   |
| --------------- | ------------------------ | -------------------------------------------------------- |
| `notifications` | `Sequence[Notification]` | All live notifications (newest first).                    |
| `unread_count`  | `int`                    | Count of `not is_read` notifications (drives the badge).  |
| `progress`      | `float \| None`          | Weighted aggregate of per-notification `progress`; `None` if none report progress. |

Each `Notification` carries `id`, `title`/`content`, `importance`, `display_type`
(`BACKGROUND`/`FLASH`/`STICKY`), optional `chime`, `blink`, `actions`, `extra_information`, and
`progress`/`progress_weight`. A stable `id` means re-adding replaces (not stacks) the notification.

## Actions & Events

Per the store contract, **events are emitted only from the reducer**. Stack push/pop are returned as
*child actions* on the ordered action queue (not from event handlers) so they can't race — event
handlers run in concurrent worker threads and would land out of order.

| Action                          | Reducer result                                                        |
| ------------------------------- | -------------------------------------------------------------------- |
| `NotificationsAddAction`        | Upserts by `id`; recomputes `unread_count`/`progress`; → `StackPushNotificationAction`, `NotificationsDisplayEvent`, and (conditionally) `RgbRingBlinkAction` + `AudioPlayChimeAction`. |
| `NotificationsDisplayAction`    | → `NotificationsDisplayEvent(index,count)` (re-show without mutating the list). |
| `NotificationsClearAction`      | Removes one notification (by identity); → `StackPopNotificationAction`, `NotificationsClearEvent`. |
| `NotificationsClearByIdAction`  | Removes all with a given `id`; → pop + one `NotificationsClearEvent` per removed. |
| `NotificationsClearAllAction` / `FinishAction` | Clears everything; → pop + clear event per notification. |

`NotificationsAddAction` **always** returns a `StackPushNotificationAction` (idempotently): a
notification's stack item lives for its whole lifecycle and the *view computation* decides whether to
render it from `display_type` (BACKGROUND is filtered out; STICKY/FLASH own the screen). Pops only
happen on real clear/dismiss — no push/pop churn across the STICKY→BACKGROUND→FLASH lifecycle.

## Runtime & Setup

`setup()` (`ubo_handle.py:234`) registers the reducer, then calls
`_register_notification_action_handlers()`, which subscribes two event handlers:

- **`on_display`** (`NotificationsDisplayEvent`) → `_refresh_notification_action_handlers`: clears any
  stale handlers for that `id`, then registers fresh index-based handlers
  (`notification:action:{id}:{index}`), the "extra info" reader, and (unless suppressed) the dismiss
  handler. Rebinding on every display is essential — a notification re-displayed under the same `id`
  with *different* actions (e.g. a multi-step download flow) must bind buttons to the current actions,
  not the stale ones.
- **`on_clear`** (`NotificationsClearEvent`) → unregister that notification's handlers.

Registered handler ids are tracked in the module-level `_registered_actions` dict (guarded by
`_actions_lock`) — a module container, not a global. Key handler behaviors:

- **Dismiss** (`_create_dismiss_handler`) looks the notification up by `id` and dispatches
  `NotificationsClearAction` for *that* one — it deliberately does **not** blind-pop the stack top,
  which would dismiss a different stacked notification.
- **Action items** (`_create_action_handler`) run either a `NotificationDispatchItem.store_action`
  (serializable — dispatched directly) or a registered `action_id`, then apply close/dismiss per the
  item's `close_notification`/`dismiss_notification` flags.
- **Extra info** (`_create_extra_info_handler`) dispatches `SpeechSynthesisReadTextAction` to read the
  notification's `extra_information` aloud.

## User Interface

Headless in the settings sense — no settings entry or dynamic menu of its own. Notifications render as
overlays the *view computation* derives from the slice + navigation stack; the GUI/TUI clients draw
whatever the store pushes (the dumb-client pattern). Notification action buttons are wired through the
core action registry (`register_action` / `NOTIFICATION_*_PREFIX` ids in
`store/core/constants.py`).

## Cross-Service Interactions

- **Produced by many services** — audio (driver install), docker, wifi, assistant, etc. all dispatch
  `NotificationsAddAction`.
- **Dispatches to** `000-audio` (`AudioPlayChimeAction`), `rgb_ring` (`RgbRingBlinkAction`), and the
  core navigation stack (`StackPush/PopNotificationAction`).
- **Cooperates with** `010-speech-synthesis`, which also subscribes to `NotificationsDisplayEvent` to
  auto-read `extra_information` when the screen reader is on.

## Configuration

No env vars or secrets. Notable constants: `NOTIFICATIONS_FLASH_TIME` (`ubo_app.constants`), the
`Importance`→icon/color/blink-repetition tables, and the `notification:*` action-id prefixes in
`store/core/constants.py`.

## Testing & Development Notes

Related tests:

| Test                                                | Tier        | What it covers                                                |
| --------------------------------------------------- | ----------- | ------------------------------------------------------------ |
| `tests/integration/test_services.py`                | Integration | `notifications` service registers; store snapshot matches.   |
| `tests/store/test_notification_action_rebind.py`    | Unit        | Re-display rebinds index-based action handlers to current actions. |
| `tests/store/test_notification_stack_reconciliation.py` | Unit    | Reducer returns stack push/pop on the ordered queue (no race). |
| `tests/store/test_notification_dismiss_stack.py`    | Unit        | Dismissing one of several stacked notifications keeps the others. |
| `tests/store/test_notification_overflow.py`         | Unit        | Action pagination (`>PAGE_SIZE` actions → `total_pages`).    |
| `tests/store/test_notification_scroll.py`           | Unit        | Single-page text scroll + multi-page item scroll.            |
| `tests/flows/test_notification_lifecycle.py`        | Flow (E2E)  | Deterministic add/clear sequences with window + store snapshots. |
| `tests/flows/test_notification_dismiss_stack.py`    | Flow (E2E)  | Real-keypad dismiss of stacked notifications (survivor stays). |
| `tests/flows/test_notification_extra_info_back.py`  | Flow (E2E)  | BACK from the ⓘ extra-info page reveals (not dismisses) the parent. |
| `tests/flows/test_notification_scroll.py`           | Flow (E2E)  | Multi-page + text-overflow scroll with snapshots.            |

This service is well covered — regressions here have historically been subtle stack/race bugs, hence
the dedicated flow tests.

**Maintenance when you change this service:**

- **State shape** (`NotificationsState`/`Notification`) or default rendering → regenerate store/window
  snapshots (never hand-edit them); updates the `test_services.py` and flow-test fixtures.
- **Reducer branch** (add/clear semantics, stack push/pop) → cover in the matching
  `tests/store/test_notification_*` unit test; the stack-reconciliation invariant (push/pop from the
  reducer, never from an event handler) must be preserved.
- **Action-handler wiring** (`ubo_handle.py`) → the rebind and dismiss-stack behaviors are guarded by
  `test_notification_action_rebind.py` and `test_notification_dismiss_stack.py`; extend those rather
  than adding an E2E when the logic is pure.
- Flow tests boot a real app over gRPC and render — run them in Docker or on-device (they're
  unreliable on macOS; see the memory note on `tests/flows` needing Docker).

To exercise manually: raise a STICKY notification, add a second, then dismiss the top via the keypad
X and confirm the one underneath survives; open a notification's ⓘ page and press BACK.
