# Speech Synthesis Service (`010-speech-synthesis`)

## Overview

The Speech Synthesis service is the device's **screen reader** — it reads notification "extra
information" (and remote read requests) aloud. It no longer owns any TTS engine: it forwards every
read request to the assistant's TTS pipeline (which synthesizes and plays back through `000-audio`),
and exposes a single "Screen Reader" on/off toggle (plus a "Prefer Local" option) under Accessibility
settings. Think of it as a thin routing/accessibility layer over the assistant's TTS.

It loads in the `010-` tier alongside `010-notifications`, since its primary job — auto-reading
notifications — depends on the notifications service being present.

## Files

| Path               | Purpose                                                                        |
| ------------------ | ------------------------------------------------------------------------------ |
| `ubo_handle.py`    | Registration; wires the reducer and returns `init_service()`'s subscriptions.   |
| `setup.py`         | Runtime: Screen Reader menu, toggle handlers, auto-read hook, TTS deep-link, forwarding. |
| `reducer.py`       | Pure reducer for the `speech_synthesis` slice.                                  |
| `tts_selection.py` | Pure helpers: pick the highest-priority configured *local* TTS; detect any configured TTS. |

Store types: [`ubo_app/store/services/speech_synthesis.py`](../../store/services/speech_synthesis.py).
For the action→reducer→event→subscriber model, see
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## State

Slice: `state.speech_synthesis` —
[`SpeechSynthesisState`](../../store/services/speech_synthesis.py):

| Field                      | Type   | Meaning                                                            |
| -------------------------- | ------ | ---------------------------------------------------------------- |
| `is_screen_reader_enabled` | `bool` | Gates *automatic* notification readout; persisted. Default `False`. |
| `is_prefer_local_enabled`  | `bool` | Prefer a local TTS engine (Piper→Kokoro) over the assistant default; persisted. |

`ReadableInformation` (the payload read aloud) carries `text` plus per-engine variants; deprecated
`speech_rate`/`engine` fields on `SpeechSynthesisReadTextAction` are kept only for backward
compatibility with generated clients.

## Actions & Events

Per the store contract, **events are emitted only from the reducer**; `setup.py` subscribes and does
the forwarding side effect. The screen-reader toggle gates only the *automatic* readout in the
notification-display handler — **not** the reducer, so a direct `SpeechSynthesisReadTextAction`
always reads regardless of the toggle.

| Action                              | Reducer result                                                     |
| ----------------------------------- | ----------------------------------------------------------------- |
| `SpeechSynthesisReadTextAction`     | → `SpeechSynthesisSynthesizeTextEvent(information)` → `_synthesize`. |
| `SpeechSynthesisSetIsEnabledAction` | Sets `is_screen_reader_enabled`.                                  |
| `SpeechSynthesisSetPreferLocalAction`| Sets `is_prefer_local_enabled`.                                  |

`_synthesize` (`setup.py:95`) forwards to the assistant by dispatching `AssistantSynthesizeAction`,
choosing a local provider only when "Prefer Local" is on and one is configured (`_preferred_tts_provider`).

## Runtime & Setup

`init_service()` (`setup.py:286`) returns a `Subscriptions` list and:

- **Registers action handlers** (`allow_reregister=True`): toggle screen reader, toggle prefer-local,
  and "open TTS settings" (the deep-link).
- **Registers the settings entry** under `SettingsCategory.ACCESSIBILITY` ("Screen Reader") and a path
  matcher (`create_settings_path_matcher('speech_synthesis:', SCREEN_READER_MENU_ID)`).
- **Persists** `speech_synthesis:is_screen_reader_enabled` and `:is_prefer_local_enabled`.
- **Subscribes** three events:
  - `SpeechSynthesisSynthesizeTextEvent → _synthesize` (forward to assistant TTS).
  - `NotificationsDisplayEvent → _auto_read_notification` — the single renderer-agnostic auto-read
    hook, gated by the toggle and de-duplicated via `_auto_read_cache` (a module dict) so repeated
    displays of the same notification id don't re-read.
  - `NotificationsClearEvent → _forget_notification` — drops the dedup entry so a re-fired
    notification reads again.

The **dynamic menu** is rebuilt by `update_screen_reader_dynamic_menu` (`setup.py:227`), an
`@store.autorun` over the two flags plus `assistant.provider_setup_status`; when no TTS is configured
it prepends a "Set Up Engine" item and shows a warning sub-heading. Toggling the reader on with no TTS
configured raises a sticky notification whose "Set up" action deep-links to the assistant's
Text-to-Speech settings (`_tts_settings_deeplink` rebuilds the full path from root, including `main`).

## User Interface

- **Settings entry:** `SettingsCategory.ACCESSIBILITY` → "Screen Reader".
- **Dynamic menu:** `SCREEN_READER_MENU_ID = 'speech-synthesis:screen-reader'` (dumb UI via
  `UpdateDynamicMenuAction`) with the Screen Reader and Prefer Local toggles.
- **Action ids:** `speech-synthesis:toggle-screen-reader`, `:toggle-prefer-local`,
  `:open-tts-settings`.
- **Path matcher:** registered for `speech-synthesis:settings`.

## System / Hardware Integration

None directly — this service performs no audio I/O and loads no TTS model. Synthesis and playback are
delegated to the assistant pipeline + `000-audio`.

## Cross-Service Interactions

- **Reads** `state.assistant.provider_setup_status` to know which TTS engines are set up (and picks a
  local one via `tts_selection.py`).
- **Dispatches** `AssistantSynthesizeAction` into `090-assistant` (the actual TTS work) and
  `NotificationsAddAction` into `010-notifications` (the "no TTS configured" warning).
- **Subscribes** to `010-notifications`' display/clear events for auto-read.

## Configuration

- Persisted keys: `speech_synthesis:is_screen_reader_enabled`, `:is_prefer_local_enabled`.
- Constants in `setup.py`: menu/action ids, `NO_TTS_NOTIFICATION_ID`, and `ASSISTANT_TTS_MENU_KEY`
  (`assistant:tts`) — the deep-link target owned by the assistant service.
- Local TTS priority (`LOCAL_TTS_PROVIDERS = (PIPER, KOKORO)`) in `tts_selection.py`.
- No secrets.

## Testing & Development Notes

Related tests:

| Test                                            | Tier        | What it covers                                                    |
| ----------------------------------------------- | ----------- | --------------------------------------------------------------- |
| `tests/integration/test_services.py`            | Integration | `speech_synthesis` service registers; store snapshot matches.   |
| `tests/store/test_speech_synthesis_reducer.py`  | Unit        | Reducer: `SetIsEnabled` flips the flag; `ReadText` always → `SynthesizeTextEvent` (toggle-independent). |
| `tests/store/test_tts_selection.py`             | Unit        | `first_configured_local_tts` priority (Piper→Kokoro, `None` fallback) + `has_any_tts_configured`. |
| `tests/navigation/test_speech_synthesis_deeplink.py` | Navigation | The "Set up TTS" notification action pops to root and rebuilds the assistant TTS path. |

This service is well covered by pure unit tests — favor extending them over E2E.

**Maintenance when you change this service:**

- **State shape** (`SpeechSynthesisState`) or the dynamic-menu output → regenerate store/window
  snapshots (never hand-edit them); updates the `test_services.py` fixture.
- **Reducer branch** → extend `tests/store/test_speech_synthesis_reducer.py`. Keep the invariant that
  the reducer never gates on the screen-reader toggle (the gate lives in `_auto_read_notification`).
- **Local-TTS selection** (`tts_selection.py`) → update `tests/store/test_tts_selection.py`; the keys
  in `provider_setup_status` must match each engine's `name`/`AssistantTTSName` value.
- **Deep-link path** (`_tts_settings_deeplink`) is coupled to the assistant's TTS matcher — the path
  must start `('main','settings','Assistant',…)` or child pages dead-end; changes are guarded by
  `test_speech_synthesis_deeplink.py`.
- No hardware to mock here; the assistant/audio side is where real synthesis is verified on-device.

To exercise manually: Settings → Accessibility → Screen Reader, toggle it on with no TTS set up
(expect the "Set up" notification), then configure a TTS engine and confirm a notification's ⓘ text is
read aloud.
