# Users Service (`050-users`)

## Overview

The Users service manages system (Linux) user accounts on the device: listing accounts (live, from
AccountsService over D-Bus), creating a new account, resetting a user's password, and deleting a
user — each surfacing generated credentials or confirmations as notifications. Account mutation is
privileged and delegated to the system manager; the account *list* is observed directly over D-Bus.

It loads in the `050-` tier (system/remote-access services). Accounts pair with the remote-access
services (SSH, RPi Connect, VSCode) in this band, giving remote logins real users to authenticate as.

## Files

| Path            | Purpose                                                                              |
| --------------- | ----------------------------------------------------------------------------------- |
| `ubo_handle.py` | Service registration (`service_id='users'`); returns `init_service()`'s subscriptions. |
| `setup.py`      | Runtime: D-Bus account listing/monitoring, event handlers, dynamic menus, matcher.  |
| `reducer.py`    | Reducer for the `users` slice; maps mutation actions → events.                       |

State/action/event types live in
[`ubo_app/store/services/users.py`](../../store/services/users.py).

## State

Slice: `state.users` — [`UsersState`](../../store/services/users.py):

| Field   | Type                          | Meaning                                                     |
| ------- | ----------------------------- | ---------------------------------------------------------- |
| `users` | `list[UserState] \| None`     | Known accounts; `None` while the first D-Bus load is pending (menu shows "Loading…"). |

`UserState` carries `id` (username) and `is_removable` (`True` for every account except `ubo`).

## Actions & Events

Per the store contract, **events are emitted only from the reducer**; `setup.py` subscribes to them
and performs the async/privileged side effects. This request → event → side-effect split keeps the
reducer pure.

| Action                     | Event emitted → handler in `setup.py`                          |
| -------------------------- | ------------------------------------------------------------- |
| `UsersCreateUserAction`    | `UsersCreateUserEvent` → `create_account`                     |
| `UsersDeleteUserAction(id)`| `UsersDeleteUserEvent(id)` → `delete_account` (confirm first) |
| `UsersResetPasswordAction(id)`| `UsersResetPasswordEvent(id)` → `reset_password`          |
| `UsersSetUsersAction`      | Replaces `users` (dispatched by the D-Bus listeners; no event). |

## Runtime & Setup

`init_service()` (`setup.py:322`) is **async** (`ubo_handle.py` awaits it) and returns a
`Subscriptions` list for clean teardown. It:

1. Registers the Settings entry (`SettingsCategory.SYSTEM`, label **Users**, icon `󰡉`, `priority=1`)
   and a custom `_users_path_matcher` (resolving both the list and per-user detail pages).
2. Opens the system bus and proxies AccountsService, then seeds the store with the current accounts:

   ```python
   accounts_service = AccountsInterface.new_proxy(
       bus=bus,
       service_name='org.freedesktop.Accounts',
       object_path='/org/freedesktop/Accounts',
   )
   store.dispatch(UsersSetUsersAction(users=await get_users()))
   ```

3. Starts `monitor_user_added()` / `monitor_user_deleted()` tasks that re-list on the AccountsService
   `user_added` / `user_deleted` D-Bus signals — live, event-driven updates rather than polling.
4. Returns `store.subscribe_event(...)` for the three mutation events plus the two monitor tasks'
   `.cancel` callbacks.

`update_users_dynamic_menu` (`setup.py:273`) — `@store.autorun(lambda state: state.users)` — rebuilds
the `users:main` menu (an "Add" item plus one entry per user) and, for each user, registers per-user
action handlers and a `users:user:{id}` detail menu (Reset Password / Delete).

The `delete_account` handler shows a **confirmation** sticky notification and awaits an
`asyncio.Future` (resolved by the confirm action / cancelled on close) before issuing the delete —
credentials from create/reset are shown in a sticky "Account Info" notification.

## User Interface

- **Settings entry:** `SettingsCategory.SYSTEM`, label **Users** (icon `󰡉`); it has **no
  `action_id`** — navigation resolves through the custom path matcher.
- **Dynamic menus:** `USERS_MENU_ID = 'users:main'` (list) and per-user `users:user:{id}` detail
  menus, all via `UpdateDynamicMenuAction` (dumb UI).
- **Action handlers:** `users:add`, and per-user `users:open-user:{id}`, `users:reset-password:{id}`,
  `users:delete:{id}`. Per-user handlers are tracked in `_user_detail_action_ids` and
  unregistered/re-registered as the list changes (never a global).
- **Path matcher:** custom `_users_path_matcher` registered under `users:settings`.

## System / Hardware Integration

- **AccountsService over D-Bus** (`org.freedesktop.Accounts`, via
  `ubo_app.utils.dbus_interfaces.AccountsInterface`/`UserInterface`) for listing and change signals.
- **Privileged account mutation** via the system manager:
  `send_command('users', 'create'|'delete'|'reset_password', [id], has_output=True)` — create/reset
  return `username:password`.

## Cross-Service Interactions

None at the store level. Dependencies are the **system manager** (privileged `users` commands), the
**system D-Bus** (AccountsService), `010-notifications` (credentials/confirmations/errors), and the
core menu/settings infrastructure. The generated credentials reference SSH password auth, tying this
service conceptually to `050-ssh`.

## Configuration

No env vars or secrets. The `ubo` account is treated as non-removable (`is_removable=False`). The
only constant is `USERS_MENU_ID = 'users:main'`.

## Testing & Development Notes

Related tests:

| Test                                 | Tier        | What it covers                                                      |
| ------------------------------------ | ----------- | ------------------------------------------------------------------ |
| `tests/integration/test_services.py` | Integration | Asserts the `users` service registers and the store snapshot matches. |

> There is currently **no dedicated unit test** for the Users reducer — it is exercised only via the
> all-services registration test. The reducer is pure and the action → event mapping is easy to cover
> (dispatch `UsersCreateUserAction`/`UsersDeleteUserAction(id)`/`UsersResetPasswordAction(id)` and
> assert the emitted events; feed `UsersSetUsersAction` and assert `users`). Adding
> `tests/store/test_users_reducer.py` is a good first contribution if you touch this service.

**Maintenance when you change this service:**

- **State shape** (`UsersState`/`UserState`) or dynamic-menu output → regenerate store/window
  snapshots (never hand-edit); this updates the `test_services.py` fixture.
- **Reducer branches / new action→event mapping** → add a `tests/store` unit test, preferred over a
  flaky E2E.
- Runtime depends on the system D-Bus (AccountsService) and the system manager for `users`
  operations — both are unavailable/mocked on a dev host, so verify create/reset/delete on-device.

To exercise manually: Settings → System → Users, Add an account (note the generated credentials),
open a user to Reset Password, and Delete (confirm the prompt) while watching the list update from
the D-Bus signals.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the service → action → reducer → state → event flow and the dumb-client architecture.
