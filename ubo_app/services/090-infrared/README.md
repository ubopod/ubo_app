# Infrared Service (`090-infrared`)

## Overview

The infrared service turns the device into a two-way IR remote: it can **send** the built-in
keypad as IR codes (propagate mode), **receive** IR codes and replay them either as keypad presses
or as bound store actions, and **register** new remote keys by learning a signal repeated five
times. Sending goes through `ir-ctl`; receiving streams codes from the privileged system manager.

It loads in the `090-` application tier — it's a hardware-driving consumer that depends on the
keypad, RGB-ring, notifications, and the bindable-actions registry being available.

For the action/event/store model, see
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## Files

| Path            | Purpose                                                                                    |
| --------------- | ----------------------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration; registers the reducer and returns `init_service()`'s subscriptions.         |
| `setup.py`      | Runtime: IR send/receive over `ir-ctl`/system manager, registration flow, dynamic menus, bindable actions. |
| `reducer.py`    | Pure reducer for the `infrared` slice; keypad↔IR-code mapping, registration state machine, bound-action dispatch. |

Store types: [`ubo_app/store/services/infrared.py`](../../store/services/infrared.py).

## State

Slice: `state.infrared` — [`InfraredState`](../../store/services/infrared.py):

| Field                                    | Type                     | Meaning                                                        |
| ---------------------------------------- | ------------------------ | ------------------------------------------------------------- |
| `should_propagate_keypad_actions`        | `bool`                   | Emit IR codes for keypad presses (persisted).                 |
| `should_receive_keypad_actions`          | `bool`                   | Listen for IR codes and act on them (persisted).              |
| `is_registering_device`                  | `bool`                   | A learn-a-key session is in progress.                         |
| `registration_signal_counts`            | `dict[str, int]`         | Per-code repeat counter during registration (needs 5).        |
| `original_should_receive_keypad_actions` | `bool \| None`           | Saved `should_receive` to restore after registration.         |
| `registered_devices`                     | `list[InfraredDevice]`   | Learned keys: `name`, `protocol`, `scancode`, `description`, `bound_action_key` (persisted). |

## Actions & Events

Events are emitted **only from the reducer**; `setup.py` subscribes and performs the async /
privileged / registry side effects.

| Action (in)                        | Reducer result                                                         |
| ---------------------------------- | --------------------------------------------------------------------- |
| `InfraredSendCodeAction`           | `RgbRingBlinkAction` + `InfraredSendCodeEvent` → `_send_code` (`ir-ctl`). |
| `InfraredSetShouldPropagateAction` | Sets `should_propagate_keypad_actions`.                               |
| `InfraredSetShouldReceiveAction`   | Sets `should_receive_keypad_actions` (an autorun starts/stops the receive loop). |
| `InfraredRegisterDeviceAction`     | Enters registering state; → `InfraredDeviceRegistrationStartedEvent`. |
| `InfraredHandleReceivedCodeAction` | While registering: counts repeats, at 5 → `InfraredDeviceRegistrationCompleteEvent`. Otherwise: replays as keypad, fires a bound action (→ `InfraredBoundActionTriggeredEvent`), or ignores. |
| `InfraredAddDeviceAction`          | Adds/updates a device; enables receive if the key has a bound action. |
| `InfraredRemoveDeviceAction`       | Removes a device by `(protocol, scancode)`.                          |
| `InfraredSetIsRegisteringDeviceAction` | Exits registering state; restores the prior receive flag.         |
| `KeypadKeyPress/ReleaseAction`     | In propagate mode → `InfraredSendCodeAction`; BACK/HOME cancels a registration. |

## Runtime & Setup

`init_service()` (`setup.py:787`) registers the persistent stores, menus/actions, the Settings
entry, and the event subscriptions.

- **Receive loop** — `run_monitor_ir` (`@store.autorun` on `should_receive_keypad_actions`) calls
  `send_command('infrared', 'start'|'stop')` and starts/cancels `_wait_for_ir_code()`, which
  streams codes from the system manager (`has_output_stream=True`), filters `imon` noise
  (`_is_ir_noise`), and dispatches `InfraredHandleReceivedCodeAction`.
- **Send** — `_send_code` serializes IR transmits through an `asyncio.Lock`/queue and shells out to
  `ir-ctl -S <protocol>:<scancode>` with a 1 s timeout.
- **Registration flow** — `_register_device` pushes an instruction page with a 60 s countdown
  (`_run_instruction_countdown`); after five matching signals the reducer emits
  `InfraredDeviceRegistrationCompleteEvent`, and `_handle_device_registration_complete` collects a
  name/description/bound-action via `ubo_input` (a `WebUIInputDescription` whose `bound_action_key`
  SELECT is built from the bindable-actions registry).
- **Bound actions** — `_handle_bound_action_triggered` resolves `bound_action_key` against the
  registry and dispatches the produced action (the reducer stays pure). Autoruns keep one
  `infrared:send:*` bindable action per device and expose receive on/off as bindable actions.
- **Dynamic menus** — `_register_menus_and_actions` builds `infrared:main`, `infrared:manage-keys`,
  `infrared:remove-devices`, `infrared:replay-devices`, `infrared:ir-settings` via
  `UpdateDynamicMenuAction`, and registers a nested path matcher (`_infrared_path_matcher`).

## User Interface

- **Settings entry:** `RegisterSettingAppAction` under `SettingsCategory.HARDWARE`.
- **Dynamic menus (dumb UI):** `infrared:main` → Replay Keys / Manage Keys / Settings; Manage Keys
  → Add Keys / Remove Keys; per-device replay/remove rows are (re)built from `registered_devices`.
- **Settings toggles:** `infrared:ir-settings` shows Receive Keys / Propagate Keys with
  selected/unselected parameters.
- **Registration:** an instruction page (`StackPushInstructionAction`) with a live countdown, then
  a WebUI form for the device name + optional bound action.
- **Remove confirm:** a `StackPushPromptAction` Yes/Cancel prompt per device.
- **Path matcher:** `_infrared_path_matcher` (priority 1) resolves the nested infrared menu paths.

## System / Hardware Integration

- **Sending:** `ir-ctl` (LIRC) subprocess — requires the IR transmitter hardware.
- **Receiving:** privileged `send_command('infrared', 'start'|'stop'|'receive')` to the system
  manager, which owns the IR receive device; `receive` streams decoded `protocol:scancode` lines.
- **Keypad↔IR map:** `KEY_TO_INFRARED_CODES` / `INFRARED_CODES_TO_KEY` (`reducer.py:44`) translate
  the built-in keys to/from `necx` codes.

## Cross-Service Interactions

- **Keypad:** consumes `KeypadKeyPress/ReleaseAction` (propagate + registration cancel) and
  produces them (replay of received codes).
- **RGB ring:** `RgbRingBlinkAction`/`RgbRingBlankAction` for send/registration feedback.
- **Bindable-actions registry:** registers `infrared:send:*` + receive on/off; resolves a device's
  `bound_action_key` to an arbitrary store action.
- **Notifications/input:** the registration name prompt via `ubo_input`.
- **Core:** menu/instruction/prompt/stack actions and the view registry.

## Configuration

- Persisted (`register_persistent_store`): `infrared_state:should_propagate_keypad_actions`,
  `infrared_state:should_receive_keypad_actions`, `infrared_state:registered_devices` (JSON).
- Constants: `REGISTRATION_REPEAT_COUNT` (5), `MIN_ZERO_BITS_FOR_VALID_IMON`, `NO_ACTION_LABEL`,
  and the `KEY_TO_INFRARED_CODES` map.

## Testing & Development Notes

| Test                                         | Tier        | What it covers                                                  |
| -------------------------------------------- | ----------- | -------------------------------------------------------------- |
| `tests/store/test_infrared_bound_actions.py` | Unit        | Received-code → bound-action dispatch vs replay-only vs keypad fallthrough. |
| `tests/integration/test_services.py`         | Integration | Asserts the `infrared` service registers and the snapshot matches. |

> The propagate map, the 5-repeat registration state machine, and the enable-receive-on-bind logic
> have **no dedicated unit test** beyond the bound-action test — they're only exercised via the
> all-services registration test. A pure `tests/store` test feeding `KeypadKeyPressAction` in
> propagate mode, or `InfraredHandleReceivedCodeAction` five times, would be a good addition.

**Maintenance when you change this service:**

- **State shape** (`InfraredState`/`InfraredDevice`) or the dynamic-menu output → regenerate
  store/window snapshots (never hand-edit them); this feeds `test_services.py`.
- **Reducer branch** (keypad↔IR map, registration counting, bound-action emission) → add/extend a
  `tests/store/test_infrared_bound_actions.py` case; prefer a pure-reducer test over hardware E2E.
- **`ir-ctl`/system-manager changes** require real IR hardware and the privileged manager — send
  (`ir-ctl`) and receive (`send_command`) are unavailable/mocked off-device, so verify the
  send/learn/replay path on-device.

To exercise manually: Settings → Hardware → Infrared → Manage Keys → Add Keys, point a remote and
press one button five times, name it (optionally binding an action), then Replay Keys to re-transmit
it; toggle Receive/Propagate in Settings to bridge the built-in keypad over IR.
