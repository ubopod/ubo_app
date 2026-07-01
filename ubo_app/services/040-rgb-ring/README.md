# RGB Ring Service (`040-rgb-ring`)

## Overview

The RGB Ring service drives the device's NeoPixel LED ring. Other services express *intent* by
dispatching high-level ring actions (pulse, blink, spinning wheel, progress wheel, fill, rainbow,
set-all, brightness…); the reducer turns each into a text command string, emits it as an event, and
`setup.py` forwards that command to the privileged LED daemon over `send_command`. The service is
effectively a **command compiler + hardware bridge**.

It loads in the `040-` tier (peripherals, alongside `040-sensors`), after core/network so it can
give boot feedback (a startup pulse) once the store is up.

See [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the store/action/event model.

## Files

| Path            | Purpose                                                                          |
| --------------- | ------------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration (`service_id='rgb_ring'`); registers the reducer, calls `init_service()`. |
| `setup.py`      | Runtime: EEPROM gate, `RgbRingCommandEvent` subscription → `send_command`, boot pulse. |
| `reducer.py`    | Pure reducer: maps command actions → `RgbRingCommandEvent`; tracks `is_busy`.    |

Store types: [`ubo_app/store/services/rgb_ring.py`](../../store/services/rgb_ring.py) — this module
holds the whole action vocabulary (each action's `as_command()` builds the daemon command line).

## State

Slice: `state.rgb_ring` — [`RgbRingState`](../../store/services/rgb_ring.py):

| Field     | Type   | Meaning                                             |
| --------- | ------ | -------------------------------------------------- |
| `is_busy` | `bool` | Whether the ring is mid-animation (set via `RgbRingSetIsBusyAction`). |

## Actions & Events

Per the store contract, **the event is emitted only from the reducer**; `setup.py` subscribes and
performs the privileged side effect. Every concrete command action subclasses `RgbRingCommandAction`
and implements `as_command()`:

| Action                          | Reducer result                                                      |
| ------------------------------- | ------------------------------------------------------------------- |
| `RgbRingSetIsBusyAction`        | Updates `is_busy` (no event).                                       |
| `RgbRingCommandAction` (any subclass) | Builds `action.as_command()`; if non-empty → `RgbRingCommandEvent(command=<split words>)`. |

Command action families (see `store/services/rgb_ring.py`): `RgbRingSetEnabledAction`,
`RgbRingSetAllAction`, `RgbRingSetBrightnessAction`, `RgbRingBlankAction`, `RgbRingRainbowAction`,
`RgbRingPulseAction`, `RgbRingBlinkAction`, `RgbRingSpinningWheelAction`,
`RgbRingProgressWheelAction` / `…StepAction`, `RgbRingFillUptoAction`, `RgbRingFillDownfromAction`,
and `RgbRingSequenceAction` (joins sub-commands with `|`). Mixins `RgbRingWaitableCommandAction`
(adds `wait`) and `RgbRingColorfulCommandAction` (adds RGB(W) `color`) compose the argument strings.

`RgbRingCommandEvent(command: list[str])` is the single event; its handler runs `send_command('led',
*command)`.

## Runtime & Setup

`init_service()` (`setup.py:8`) is **hardware-gated by EEPROM** — it does nothing unless the device
advertises a NeoPixel LED:

```python
eeprom_data = get_eeprom_data()
if (led := eeprom_data.get('led')) is None or led.get('model') != 'neopixel':
    return

async def handle_rgb_ring_command(event: RgbRingCommandEvent) -> None:
    await send_command('led', *event.command)

store.subscribe_event(RgbRingCommandEvent, handle_rgb_ring_command)
store.dispatch(RgbRingPulseAction(repetitions=2, wait=180))
```

- **Event subscription:** `RgbRingCommandEvent → handle_rgb_ring_command`, which is the only place
  the LED daemon is invoked.
- **Boot feedback:** dispatches a two-repetition pulse so the ring signals a successful start.
- No `Subscriptions` list is returned (`init_service()` returns `None`); the subscription lives for
  the process lifetime and is skipped entirely on non-NeoPixel hardware.

## User Interface

Headless — no settings entry, menu, or status icon. The ring is a physical output driven purely by
actions from other services.

## System / Hardware Integration

- **EEPROM gate:** `get_eeprom_data()['led']['model'] == 'neopixel'` decides whether the service
  activates at all.
- **Privileged LED daemon:** all ring effects run root-side via `send_command('led', …)`; the
  service never touches GPIO/SPI directly. The command grammar is exactly the string produced by each
  action's `as_command()`.

## Cross-Service Interactions

The ring is a shared output; many services dispatch its actions (they never read its slice):

- `090-assistant` — listening/thinking feedback (e.g. `RgbRingBlinkAction`).
- `090-speech-recognition` — voice command bindings map keys like `rgb:red` to `RgbRingSetAllAction`
  (`commands.py`, `setup.py`).
- `010-notifications` — notification feedback.
- `090-infrared` — remote-triggered effects.

## Configuration

No env vars or secrets. Behavior hinges on the EEPROM `led` entry; per-action defaults (e.g. pulse
`repetitions=5`, `wait=100`, default color `(255,255,255)`) live in `store/services/rgb_ring.py`.

## Testing & Development Notes

Related tests:

| Test                                          | Tier        | What it covers                                                     |
| --------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| `tests/integration/test_services.py`          | Integration | Asserts the `rgb_ring` service registers and the store snapshot matches. |
| `tests/store/test_speech_recognition_commands.py` | Unit    | Indirectly: asserts `rgb:red` resolves to `RgbRingSetAllAction(color=red)`. |
| `tests/store/test_assistant_listening_metadata.py` | Unit   | Indirectly: asserts the assistant emits `RgbRingBlinkAction` during listening. |

> There is **no dedicated unit test** for the RGB Ring reducer or the `as_command()` builders — and
> those builders are the highest-value thing to cover, since they are pure string generators with
> tricky mixin composition and validation (e.g. `RgbRingSetBrightnessAction` raises for out-of-range
> values). Adding `tests/store/test_rgb_ring_reducer.py` asserting `as_command()` output per action
> (and that `RgbRingCommandAction` → `RgbRingCommandEvent(command=[...])`) is a strong first
> contribution.

**Maintenance when you change this service:**

- **New command action / changed `as_command()` grammar** → add/extend a pure unit test asserting the
  exact command string; the reducer just splits and wraps it in `RgbRingCommandEvent`.
- **`RgbRingState` shape** → regenerate store snapshots (never hand-edit); `test_services.py` picks
  it up.
- **Runtime is hardware/EEPROM-gated:** on a dev host (no NeoPixel EEPROM) `init_service()` returns
  early and `send_command('led', …)` is unavailable, so verify actual ring behavior on-device.

To exercise manually: on-device, trigger a listening/notification flow (or dispatch a
`RgbRingPulseAction`) and confirm the LED ring animates and the boot pulse fires at startup.
