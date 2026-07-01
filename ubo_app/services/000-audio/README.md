# Audio Service (`000-audio`)

## Overview

The Audio service owns the device's sound I/O: speaker playback (chimes, one-shot samples, and
streamed sequences such as TTS), microphone capture (streamed to the store for wake-word / speech
recognition), and the ALSA mixer controls behind the volume/mute settings. It is the single place
that touches the audio hardware — every other service *asks* for playback by dispatching an action
rather than opening a device itself.

It loads in the `000-` tier (core hardware, alongside `000-keypad`/`000-display`) because so many
later services depend on being able to play a chime or read the mic: the boot "ready" chime, the
notifications service, and the assistant pipeline all fan out from here.

## Files

| Path                | Purpose                                                                       |
| ------------------- | ----------------------------------------------------------------------------- |
| `ubo_handle.py`     | Registration; wires the reducer and returns `init_service()`'s subscriptions.  |
| `setup.py`          | Runtime: instantiates `AudioManager`, wires event handlers, volume/mute autoruns, persistence. |
| `reducer.py`        | Pure reducer for the `audio` slice; maps actions → state/events/child-actions. |
| `audio_manager.py`  | Hardware layer: ALSA/simpleaudio/pyaudio playback + capture, card discovery, mixers. |
| `constants.py`      | Mic status-icon id/priority.                                                   |
| `sounds/`           | Bundled chime WAVs: `add`, `done`, `failure`, `ready`, `volume`.               |

Store types: [`ubo_app/store/services/audio.py`](../../store/services/audio.py). For the
action→reducer→event→subscriber model, see
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## State

Slice: `state.audio` — [`AudioState`](../../store/services/audio.py):

| Field               | Type                 | Meaning                                                       |
| ------------------- | -------------------- | ------------------------------------------------------------ |
| `playback_volume`   | `float` (0–1)        | Output volume; persisted (`audio_state:playback_volume`).    |
| `is_playback_mute`  | `bool`               | Output mute; persisted.                                       |
| `capture_volume`    | `float` (0–1)        | Mic gain; persisted.                                          |
| `is_capture_mute`   | `bool`               | Mic mute; persisted on RPi, defaults **muted** for privacy elsewhere. |
| `is_recording`      | `bool`               | Whether an explicit recording is being accumulated.          |
| `recording`         | `AudioSample \| None`| The accumulated recording buffer (grown by `AudioReportSampleAction`). |

`AudioSample` carries raw `data: bytes` plus `channels`, `rate`, `width`.

## Actions & Events

Per the store contract, **events are emitted only from the reducer**; `setup.py` subscribes to them
and performs the blocking hardware I/O off the store loop. Some actions instead resolve to *child
actions* (kept pure — no side effects in the reducer).

| Action                          | Reducer result                                                        |
| ------------------------------- | -------------------------------------------------------------------- |
| `AudioInstallDriverAction`      | → `AudioInstallDriverEvent` → `_install_driver` (privileged install). |
| `AudioSetVolumeAction(OUTPUT)`  | Sets `playback_volume`; → `AudioPlayChimeEvent('volume')` as feedback. |
| `AudioSetVolumeAction(INPUT)`   | Sets `capture_volume`.                                                |
| `AudioChangeVolumeAction`       | → an `AudioSetVolumeAction` clamped to 0–1 (child action).            |
| `AudioSetMuteStatusAction(INPUT)`| Sets `is_capture_mute`; → `StatusIconsRegisterAction` (mic glyph).   |
| `AudioToggleMuteStatusAction`   | → `AudioSetMuteStatusAction` with the flipped value.                 |
| `AudioPlayChimeAction`          | → `AudioPlayChimeEvent(name)` → `play_chime`.                        |
| `AudioPlayAudioSampleAction`    | → `AudioPlayAudioSampleEvent` → `play_audio` (one-shot).            |
| `AudioPlayAudioSequenceAction`  | → `AudioPlayAudioSequenceEvent` → `play_audio` (streamed chunks).   |
| `AudioStopPlaybackAction`       | → `AudioStopPlaybackEvent` → `stop_playback`.                       |
| `AudioReportSampleAction`       | Appends to `recording` if recording; → `AudioReportSampleEvent` **unless** mic is muted. |
| `AudioPlaybackDoneAction`       | → `AudioPlaybackDoneEvent(id)` (sequence-drained signal for consumers). |
| `AudioStart/Stop/ToggleRecordingAction` | Flip `is_recording` (toggle resolves to start/stop).        |
| `AudioPlayRecordingAction`      | → `AudioPlayAudioSampleEvent` of the stored recording (only if not recording). |

Note the mic-mute gate lives in the reducer: `AudioReportSampleAction` still grows the explicit
recording buffer, but emits **no** `AudioReportSampleEvent` while `is_capture_mute` — so speech
recognition never sees muted audio.

## Runtime & Setup

`init_service()` (`setup.py:119`) constructs a single `AudioManager` and returns a `Subscriptions`
list (event unsubscribes + `audio_manager.close` + view-dependency unregisters) for clean teardown.

- **Boot chime:** waits on `audio_manager.initialized` then dispatches `AudioPlayChimeAction('ready')`
  so the `ready.wav` chime plays once the card is up.
- **Mixer autoruns:** `set_playback_volume`, `set_capture_valume`, `set_playback_mute`
  (`setup.py:160`–`:170`) push slice changes down into `AudioManager` → ALSA mixers.
- **Event handlers:** `play_chime` loads a bundled WAV and re-dispatches it as an
  `AudioPlayAudioSampleAction`; `play_audio` runs `play_sample`/`play_sequence` on a worker thread
  via `to_thread` (each in its own event loop); `stop_playback` calls `simpleaudio.stop_all()` and
  clears the sequence buffers.
- **View dependencies:** registers a home-view volume provider and a status-bar recording indicator.
- **Persistence:** `register_persistent_store` for the four volume/mute keys.
- **Privileged install:** `_install_driver` (`setup.py:69`) shows a sticky "Installing driver…"
  notification and calls `send_command('audio', 'install', …)`.

## System / Hardware Integration

`AudioManager` (`audio_manager.py:112`) discovers the `wm8960` card index from EEPROM + `alsaaudio`
(`find_card_index`, retried), and drives three distinct playback paths:

- **`play_sample`** (`audio_manager.py:282`) — one-shot playback via **`simpleaudio`** (PCM buffer,
  `wait_done()`), used for chimes, recordings, and one-shot TTS. Retries and reports
  `SimpleaudioError` to `ubo-system`.
- **`play_sequence`** (`audio_manager.py:345`) — streamed, index-ordered chunks with an
  end-of-stream `sample=None` sentinel; uses **`pyaudio`** off-device and **`alsaaudio` PCM** on the
  device. This is the path for live/streamed TTS. A ~1 s empty-buffer fallback logs a warning if a
  producer forgets the sentinel.
- **`stream_mic`** (`audio_manager.py:635`) — continuously reads the (exclusive) ALSA/pyaudio capture
  device, resamples to `SPEECH_RECOGNITION_FRAME_RATE` with `soxr`, and dispatches
  `AudioReportSampleAction`.

`IS_RPI` selects the backend: on the Pi, capture/sequence-playback go through `alsaaudio`; on a dev
host (`not IS_RPI`) a `pyaudio.PyAudio()` instance is used instead. The ALSA capture device is
exclusive, so `close()`/`_release_input()` are careful to drain the reader before closing the PCM
(avoids a shutdown deadlock).

## Cross-Service Interactions

- Dispatches into `010-notifications` (driver-install progress/result) and
  `status_icons` (mic-state glyph).
- Consumed by nearly everything that makes sound: `010-notifications` (chimes), `010-speech-synthesis`
  / the assistant TTS pipeline (`AudioPlayAudioSequenceAction`), and speech recognition consumes the
  `AudioReportSampleEvent` mic stream.
- Delegates privileged driver install / failure reporting to the system manager via `send_command`.

## Configuration

- Persisted keys: `audio_state:playback_volume`, `:is_playback_mute`, `:capture_volume`,
  `:is_capture_mute`.
- `INPUT_FRAME_RATE = 48_000`, `INPUT_CHANNELS = 2`, `INPUT_PERIOD_SIZE` (50 ms) in
  `audio_manager.py`; `SPEECH_RECOGNITION_FRAME_RATE` from `ubo_app.constants`.
- Mic status-icon id/priority in `constants.py`.
- No secrets.

## Testing & Development Notes

Related tests:

| Test                                          | Tier        | What it covers                                                     |
| --------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| `tests/integration/test_services.py`          | Integration | Asserts the `audio` service registers and the store snapshot matches. |
| `tests/store/test_mic_buffer.py`              | Unit        | The rolling mic buffer that consumes `AudioReportSample*` (speech-recognition side). |
| `tests/navigation/test_keypad_reducer.py`     | Navigation  | Exercises `AudioChangeVolumeAction` (volume keys) alongside keypad handling. |

> There is currently **no dedicated unit test for the audio reducer or `AudioManager`**. The reducer
> is pure and has several non-trivial branches worth covering directly — the mic-mute gate on
> `AudioReportSampleAction` (no event when muted), `AudioChangeVolumeAction` clamping to 0–1, and the
> volume-change chime. Adding `tests/store/test_audio_reducer.py` is a good first contribution if you
> touch this service.

**Maintenance when you change this service:**

- **State shape** (`AudioState`) or new default values → regenerate store/window snapshots (never
  hand-edit them); this updates the `test_services.py` fixture.
- **Reducer branch** (new action / changed event mapping) → add/extend a `tests/store` pure-reducer
  unit test; prefer that over an E2E audio flow.
- **Hardware paths** (`play_sample`/`play_sequence`/`stream_mic`) can't run on CI: playback goes
  through `simpleaudio`, which tests mock when `not IS_RPI` (see
  `tests/fixtures/mock_environment.py` and the memory note on audio playback paths). Real ALSA/pyaudio
  behavior — card discovery, mixer control, capture — must be verified **on-device**.
- **Bundled chimes:** adding a `sounds/<name>.wav` makes it playable via `AudioPlayChimeAction(name)`;
  keep the enum in `store/services/notifications.py::Chime` in sync if it's a semantic chime.
- **The `play_sequence` sentinel contract** (`sample=None` end-of-stream) is load-bearing — new
  streamed-audio producers must send it or eat the ~1 s fallback latency.

To exercise manually: change the volume from the home screen (hear the volume chime), toggle mic mute
(watch the status-bar glyph), and confirm the boot `ready` chime plays after an audio restart.
