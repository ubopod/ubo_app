# Keypad Service (`000-keypad`)

## Overview

The keypad service turns physical button input into store actions. On a Ubo Pod it reads the
seven-key membrane keypad plus the mic-mute switch through an **AW9523 I2C GPIO expander** (interrupt
on a GPIO pin, one lifecycle thread per button), and translates each press / hold / release — and
multi-key chords — into navigation, volume, assistant, screenshot, and recording actions. The reducer
that maps buttons to behavior is pure and runs on **every** platform, because the same key actions
also arrive from the GUI client, the web UI, and infrared, not just the hardware.

It loads in the `000-` (core hardware) tier: input must be available as early as display and system
metrics. See
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the action/event flow.

## Files

| Path            | Purpose                                                                             |
| --------------- | ----------------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration; returns `init_service()`'s subscription list.                         |
| `setup.py`      | Hardware `Keypad` class (I2C/GPIO, per-button lifecycle threads) + the context-sync autorun. |
| `reducer.py`    | Pure reducer: maps key/chord actions → navigation/audio/assistant/system actions and events. |

Store types: [`ubo_app/store/services/keypad.py`](../../store/services/keypad.py).

## State

Slice: `state.keypad` — [`KeypadState`](../../store/services/keypad.py):

| Field                | Type   | Meaning                                                                     |
| -------------------- | ------ | -------------------------------------------------------------------------- |
| `is_consumed`        | `bool` | The current press was "used up" (e.g. it woke a blanked screen or started a hold), so its release is a no-op. |
| `depth`              | `int`  | Menu-stack depth (mirrored from `state.main.stack`).                        |
| `is_on_notification` | `bool` | Top of the stack is a notification view.                                    |
| `is_on_chat`         | `bool` | Top of the stack is the chat overlay.                                       |
| `is_on_application`  | `bool` | Top is a render/application view (owns up/down itself, so no volume shortcut). |
| `is_display_blanked` | `bool` | Screen is blanked (mirrored from `state.display`).                          |

The last five fields are **mirrored** into this slice by the service's autorun via
`KeypadReportContextAction`, so the reducer never reaches into other slices mid-reduce.

## Actions & Events

The reducer maps input actions (`KeypadKeyPressAction`, `KeypadKeyHoldAction`,
`KeypadKeyUnholdAction`, `KeypadKeyReleaseAction`) and the context action into cross-service actions
and events. Events are emitted only from the reducer. Key mappings:

| Input (chord)                     | Result                                                                 |
| --------------------------------- | --------------------------------------------------------------------- |
| Press on blanked screen           | `DisplayUnblankAction` (consumes the press).                          |
| `KeypadReportContextAction`       | Patches the mirrored context fields (no side effects).               |
| `UP` / `DOWN` at depth 1 (home)   | `AudioChangeVolumeAction ±0.05` (OUTPUT) + activity.                  |
| `UP` / `DOWN` elsewhere           | `MenuScrollAction(UP/DOWN)` + activity.                              |
| `L1` / `L2` / `L3` (single)       | → `MenuChooseByIndexEvent(index=0/1/2)` + activity.                  |
| `HOME` press at depth 1           | `AssistantStartListeningAction` (press mode) + activity.             |
| `HOME` hold at depth > 1          | `AssistantStartListeningAction` (hold mode), consumes.              |
| `HOME` unhold / release          | `AssistantStopListeningAction` (+ `MenuGoHomeAction` on release).   |
| `BACK` release                    | `MenuGoBackAction`.                                                  |
| `HOME`+`L1`                       | `TakeScreenshotAction`.                                              |
| `HOME`+`L2`                       | → `SnapshotEvent` (store snapshot).                                  |
| `HOME`+`L3`                       | `ToggleRecordingAction` (action recording).                          |
| `BACK`+`L1` / `L2` / `L3`         | `AudioToggleRecordingAction` / `AudioPlayRecordingAction` / `ReplayRecordedSequenceAction`. |
| `HOME`+`BACK`                     | → `FinishEvent` (shut down).                                         |
| `HOME`+`UP` / `HOME`+`DOWN`       | Demo `NotificationsAddAction` (progress / spinner).                 |

Nearly every mapping also dispatches `DisplayUpdateActivityAction` to keep the screen awake.

## Runtime & Setup

Two independent pieces:

- **Context mirror (`_sync_keypad_context`, `setup.py:92`)** — `@store.autorun` over a cheap selector
  (menu depth, notification/chat/application flags, `display.is_blanked`). Whenever the derived
  context changes it dispatches `KeypadReportContextAction`, keeping `KeypadState` in sync so the
  reducer can be pure. **Active regardless of `IS_RPI`**, since key events also come from soft clients.

- **Hardware (`init_service`, `setup.py:389`)** — returns `[]` immediately if `not IS_RPI`. Otherwise
  it checks the EEPROM for an `aw9523` keypad, constructs a `Keypad()`, and returns a `cleanup` that
  releases the GPIO interrupt line:

  ```python
  eeprom_data = get_eeprom_data()
  if (keypad := eeprom_data.get('keypad')) and keypad.get('model') == 'aw9523':
      keypad_instance = Keypad()
      return [cleanup]  # button.when_pressed = None; button.close()
  ```

The `Keypad` class initializes the AW9523 over I2C, wires a `gpiozero.Button` on `INT_EXPANDER` (GPIO
5) as the interrupt, and on each interrupt (`key_press_cb`) XORs current vs previous inputs to find
the changed bit. A **press spawns a thread** (`start_button_press_lifecycle`) that dispatches
`KeypadKeyPressAction`, then — if not released within 0.5 s — `KeypadKeyHoldAction`, waits for
release, and dispatches `KeypadKeyUnholdAction` and finally `KeypadKeyReleaseAction`, each carrying
the current `pressed_keys`/`held_keys` sets so the reducer can match chords. The mic-mute switch
(index 7) dispatches `AudioSetMuteStatusAction` directly. I2C init is wrapped in `tenacity` retries
for transient `EIO` errors.

## System / Hardware Integration

- **I2C / GPIO** via `board`, `adafruit_aw9523` (AW9523 expander at `0x58`), and `gpiozero.Button`
  (interrupt on GPIO 5). Direct register writes reset/mask the expander's interrupt flags.
- **Threading:** one short-lived thread per button press drives the press→hold→unhold→release
  lifecycle without blocking the interrupt callback.
- **EEPROM detection** (`ubo_app/utils/eeprom.py`) gates hardware setup to devices that actually have
  an `aw9523` keypad.

## Cross-Service Interactions

- **Dispatches into** `030-audio` (volume, mute, recording playback/toggle), `090-assistant`
  (listening start/stop with a `KeypadTriggerSource`), `000-display` (unblank/activity),
  `010-notifications` (demo), and core navigation (`MenuScroll/GoBack/GoHome`, `MenuChooseByIndexEvent`,
  `TakeScreenshotAction`, `SnapshotEvent`, `FinishEvent`).
- **Reads** `state.main.stack` and `state.display.is_blanked` (via the autorun, guarded with
  `hasattr`) to derive context — the load-tier ordering means the display slice may not exist yet, so
  the selector defaults `is_display_blanked` to `False`.

## Configuration

No env vars. Module constants in `setup.py`: `KEY_INDEX` (bit → `Key`), `INT_EXPANDER = 5`,
`MIC_INDEX = 7`, `BUS_ADDRESS = 0x58`. Hardware paths are gated by `IS_RPI` and the EEPROM model
check.

## Testing & Development Notes

Related tests:

| Test                                        | Tier        | What it covers                                                        |
| ------------------------------------------- | ----------- | -------------------------------------------------------------------- |
| `tests/navigation/test_keypad_reducer.py`   | Unit        | The pure reducer's decision logic — context sync, wake-on-press, volume vs scroll, application-view guard, L1/L2/L3 choose-by-index, back/home. Loads the reducer by file path (hyphenated dir). |
| `tests/navigation/test_keypad_navigation.py`| Navigation  | Keypad-driven menu navigation (L1→L1→DOWN→DOWN) asserting `ViewData`/`page_index` stay in sync as a GUI client would see over gRPC. |
| `tests/integration/test_services.py`        | Integration | Asserts the `keypad` service registers and the store snapshot matches. |

`tests/fixtures/dispatch.py` provides the keypad-press helper used by higher-tier flow tests (real
gRPC keypad presses, per the project's E2E rule).

**Maintenance when you change this service:**

- **Reducer branch** (new key/chord mapping) → add a case to `tests/navigation/test_keypad_reducer.py`;
  prefer this pure-reducer unit test over a flaky E2E flow.
- **Context fields** (`KeypadState` mirrored fields) → update both the `_sync_keypad_context` selector
  and `KeypadReportContextAction`, and cover with `test_keypad_reducer.py`.
- **State shape** → regenerate store/window snapshots (never hand-edit them); this updates
  `test_services.py`.
- **Navigation semantics** → verify with `test_keypad_navigation.py`.
- Hardware paths (`Keypad`, I2C/GPIO, mic mute) only run when `IS_RPI` and the EEPROM reports an
  `aw9523` keypad, so button wiring/interrupt behavior is verifiable only on-device.

To exercise manually (on a Pod): press UP/DOWN on the home screen to change volume, `L1/L2/L3` to
select menu items, hold `HOME` to start the assistant, and `HOME`+`L1` for a screenshot.
