# Keyboard Service (`020-keyboard`)

## Overview

The Keyboard service is a **placeholder** on the Core side. Desktop keyboard input is not handled
here — it is mapped to keypad actions by the GUI client
([`ubo_app/gui/ubo_gui_client/keyboard.py`](../../gui/ubo_gui_client/keyboard.py)), which dispatches
those actions to the Core over gRPC (the dumb-client architecture). Physical keypad events come from
`000-keypad` (GPIO/I2C). This service exists mainly to reserve the `keyboard` service id and to host
the developer-facing [`shortcuts.md`](shortcuts.md) reference; its `init_service()` is a no-op.

It sits in the `020-` tier as an input-related service, but carries no runtime weight.

## Files

| Path            | Purpose                                                                    |
| --------------- | ------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration; `setup()` just calls `init_service()`. **No reducer.**       |
| `setup.py`      | `init_service()` — a documented no-op returning `[]` (no subscriptions).    |
| `shortcuts.md`  | Keypad ↔ keyboard shortcut mapping and artifact (screenshot/snapshot/recording) locations. |

There is **no store slice and no reducer** for this service — it holds no state.

## State

None. This service registers no reducer and owns no slice.

## Actions & Events

None. The service dispatches nothing and subscribes to nothing. Keyboard-derived actions (navigation,
selection, screenshot, snapshot, recording, exit) originate in the GUI client and are the *same*
keypad actions the physical keypad emits — see the mapping in [`shortcuts.md`](shortcuts.md).

## Runtime & Setup

`init_service()` (`setup.py:14`) returns `[]`. `ubo_handle.py`'s `setup()` calls it and registers the
service under id `keyboard`. There are no autoruns, subscriptions, or background tasks.

Where the real work lives:

- **Desktop keys → keypad actions:** `ubo_app/gui/ubo_gui_client/keyboard.py` maps arrows/`H`/`J`/`K`,
  `1`/`2`/`3`, `Esc`/`Backspace`, and their SHIFT/CTRL combos to keypad actions and dispatches them
  via gRPC.
- **Physical keypad:** `000-keypad` reads GPIO/I2C and dispatches the same actions.

## User Interface

None — headless placeholder. No settings entry, menu, or path matcher.

## System / Hardware Integration

None on the Core side. Keyboard capture is a GUI-client (Kivy `Window`) concern; keypad hardware is
`000-keypad`'s concern.

## Cross-Service Interactions

None directly. Conceptually it documents the shortcuts that drive the keypad action flow consumed by
navigation/core; see [`shortcuts.md`](shortcuts.md) for the SHIFT+`1`/`2`/`3` (screenshot / store
snapshot / record) and HOME/BACK combos.

## Configuration

None. Artifact output paths (documented in `shortcuts.md`): screenshots `/opt/ubo/screenshots/`,
store snapshots `/opt/ubo/snapshots/`, key recordings `/opt/ubo/recordings/`.

## Testing & Development Notes

Related tests:

| Test                                       | Tier        | What it covers                                                    |
| ------------------------------------------ | ----------- | --------------------------------------------------------------- |
| `tests/integration/test_services.py`       | Integration | Asserts the `keyboard` service registers and the store snapshot matches. |
| `tests/gui/test_keyboard.py`               | GUI         | GUI-client keyboard bindings (`gui/ubo_gui_client/keyboard.py`) — the real mapping. |
| `tests/navigation/test_keypad_reducer.py`  | Navigation  | The keypad reducer these keyboard-mapped actions feed into.      |

> This Core service has **no dedicated unit test**, which is appropriate: it has no reducer and no
> behavior to cover. The meaningful tests live on the GUI-client side (`tests/gui/test_keyboard.py`)
> and the keypad reducer (`tests/navigation/test_keypad_reducer.py`).

**Maintenance when you change this service:**

- **Adding real keyboard behavior** would mean adding a reducer/slice here — at which point add a
  `tests/store` unit test and (if it changes state shape) regenerate store/window snapshots (never
  hand-edit them).
- **Shortcut changes** belong in the GUI client (`gui/ubo_gui_client/keyboard.py`) and must be kept
  in sync with [`shortcuts.md`](shortcuts.md); update `tests/gui/test_keyboard.py` accordingly.
- Because it's a registration-only placeholder, the only thing that can break here is the service
  failing to register — caught by `tests/integration/test_services.py`.

To exercise manually: run the desktop GUI client and drive the menu with the keyboard per
[`shortcuts.md`](shortcuts.md) (arrows/HJK to move, `1`/`2`/`3` to select, SHIFT+`1` to screenshot).
