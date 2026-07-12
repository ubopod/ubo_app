# Speech Recognition Service (`090-speech-recognition`)

## Overview

The speech-recognition service is the device's offline **ears**: it streams system-microphone
audio through one or more pluggable engines to detect *wake words* (which start the assistant or a
command-listener) and to recognise short *voice commands* (intents) that fire bindable actions. It
owns the wake-phrase configuration UI, the OpenWakeWord model pool (download / upload / delete), and
the mapping from a detected phrase to an assistant behaviour.

It loads in the `090-` tier (higher-level, app-like services) because it depends on the audio input
pipeline (`audio` slice), the assistant, infrared, RGB-ring, and notifications services already
being available to consume and drive.

> Architecture background (store, dumb-client, action/event flow) lives in
> [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).
> This README covers only what is specific to this service.

## Files

| Path                                  | Purpose                                                                    |
| ------------------------------------- | -------------------------------------------------------------------------- |
| `ubo_handle.py`                       | Registration; `setup` registers the reducer then returns `init_service()`. |
| `setup.py`                            | Runtime hub (~815 lines): `EnginesManager`, autoruns, model download/delete handlers, command forms, path matcher. |
| `reducer.py`                          | Pure reducer for the `speech_recognition` slice; the wake-mode→effect map. |
| `constants.py`                        | `INTENTS_LISTENING_TIMEOUT_SECONDS` (post-wake command listen window).     |
| `abstraction/base_class.py`           | `BaseSpeechRecognitionEngine` — audio input queue + failure→disable path over `BackgroundRunningMixin`. |
| `abstraction/speech_recognition_mixin.py` | `SpeechRecognitionMixin` + `Recognition`/`SpeechRecognition`/`PhraseRecognition` — end-phrase / phrase-list recognition. |
| `abstraction/wake_word_recognition_mixin.py` | `WakeWordRecognitionMixin` + `WakeTrigger` — trigger-list wake detection. |
| `vosk_engine.py`                      | Vosk engine: speech recognition **and** wake detection; lazy Kaldi model load. |
| `openwakeword_engine.py`              | OpenWakeWord engine: confidence-scored wake detection + model download/upload/delete/scan. |
| `engines_manager.py`                  | `EnginesManager`: registry of engines, mic fan-out, trigger sync, detection routing, cleanup. |
| `mic_buffer.py`                       | `MicBuffer` — rolling N-second mic buffer dumped to WAV on assistant wake/stop phrases. |
| `pattern.py`                          | `expand_pattern()` — compact utterance-pattern → concrete phrase list.     |
| `wake_phrase_validation.py`           | Pure Kaldi-vocabulary validation + cross-phrase collision checks for phrase editing. |
| `wake_menu.py`                        | Wake-up menu tree (mode-first), trigger / Infrared / model-management forms + handlers. |
| `commands.py`                         | Bindable-action catalog, per-mode wake bindables, `DEFAULT_COMMANDS`, command load/seed. |

Store types: [`ubo_app/store/services/speech_recognition.py`](../../store/services/speech_recognition.py).

## State

Slice: `state.speech_recognition` —
[`SpeechRecognitionState`](../../store/services/speech_recognition.py):

| Field                     | Type                                    | Meaning                                                        |
| ------------------------- | --------------------------------------- | ------------------------------------------------------------- |
| `intents`                 | `list[SpeechRecognitionIntent]`         | Voice commands: phrases → bindable `action_keys`. Seeded from `DEFAULT_COMMANDS` on first run; persisted. |
| `wake_engines`            | `tuple[WakeWordEngineConfig, ...]`      | Per-engine `enabled` flag + its `WakeWordTrigger`s. Persisted; migrated from legacy keys. |
| `assistant_enabled`       | `bool`                                  | Master switch for QUICK_CHAT/CONVERSATION wake modes (INTENTS/STOP_TALKING unaffected). Persisted. |
| `openwakeword_models`     | `tuple[str, ...]`                       | OpenWakeWord model stems on disk (downloaded + uploaded). Derived from disk at startup; **not** persisted. |
| `conversation_end_phrases`| `tuple[str, ...]`                       | End-of-turn phrases consumed assistant-side. Persisted.       |
| `status`                  | `SpeechRecognitionStatus`               | `IDLE` / `INTENTS_WAITING` (standalone command window, 10 s) / `ASSISTANT_WAITING` (stage-1 matching armed alongside a quick-chat session). |
| `assistant_session_audio_source` | `str`                            | The mic of the quick-chat session stage-1 is armed for (only meaningful while `ASSISTANT_WAITING`). `''` = on-device system mic — the only source Vosk consumes, so a non-empty value (web mic) keeps the grammar disarmed. |
| `commands_catalog`        | `SpeechRecognitionCommandsCatalog`      | Trimmed mirror of `intents` (patterns pre-expanded into ≤3 sample phrases) for the assistant's `run_device_command` LLM tool. Rebuilt by the reducer at every `intents` write site; must be materialised because gRPC autoruns subscribe by *field path*, not selector. |
| `wake_word_models_status` | `tuple[WakeWordModelStatusEntry, ...]`  | Per-engine default-model download status (tuple, not enum-map, so it round-trips over gRPC). |

Each `WakeWordTrigger` carries `id`, `label`, `mode` (`WakeMode`), `value` (engine-specific: a Vosk
phrase or an OpenWakeWord model stem), and `sensitivity` (0.0–1.0, only used by confidence-scored
engines). Seed/migrated triggers get deterministic `<mode>-<index>` ids for snapshot stability;
user-added ones get uuids.

## Actions & Events

The reducer is pure — **events are emitted only from the reducer**; blocking work (downloads,
filesystem, action resolution) is done in `setup.py` event handlers.

| Action (in)                                       | Reducer result                                                  |
| ------------------------------------------------- | -------------------------------------------------------------- |
| `WakeEngineSetEnabledAction`                      | Flip an engine's `enabled` flag.                               |
| `WakeTriggerAddAction` / `WakeTriggerRemoveAction`| Add/remove a trigger (sensitivity clamped to `[0,1]`).        |
| `SpeechRecognitionSetAssistantEnabledAction`      | Set `assistant_enabled`.                                       |
| `SpeechRecognitionAdd/Update/RemoveCommandAction` | Edit the `intents` command list.                              |
| `SpeechRecognitionSetConversationEndPhrasesAction`| Replace `conversation_end_phrases`.                           |
| `SpeechRecognitionReportWakeWordDetectionAction`  | Resolve `(engine, trigger_id)` → mode → `_apply_wake_mode` (see below). |
| `SpeechRecognitionTriggerModeAction`              | Fire a mode directly (Infrared-bound; bypasses the assistant gate). |
| `WakeWordDownloadModelsAction`                    | Mark engine `DOWNLOADING` → **`WakeWordDownloadModelsEvent`** → `_handle_download_models`. |
| `WakeWordDeleteModelAction`                       | Prune pool + triggers → **`WakeWordDeleteModelEvent`** → `_handle_delete_model`. |
| `WakeWordSetAvailableModelsAction` / `WakeWordSetModelsStatusAction` | Record disk-scan results (dispatched by the service). |
| `SpeechRecognitionReportIntentDetectionAction`    | **Status-gated.** From `INTENTS_WAITING` → **`SpeechRecognitionBoundActionTriggeredEvent`**. From `ASSISTANT_WAITING` → the same event *plus* `AssistantStopTalkingAction` (stage 1 — see below). From `IDLE` → dropped; this is the exactly-once guard. |
| `SpeechRecognitionSetAssistantListeningAction`    | Arm (`IDLE` → `ASSISTANT_WAITING`) / disarm stage-1 matching. Dispatched by `setup.py`'s autorun on the assistant's `is_listening`. |
| `SpeechRecognitionRunCommandAction`               | Stage 2 — the LLM's `run_device_command` tool. Status-independent; resolves `command_id` against `intents` → **`SpeechRecognitionBoundActionTriggeredEvent`**. Unknown id is a no-op. |
| `SpeechRecognitionReportIntentTimeoutAction`      | Leave `INTENTS_WAITING`, blank the ring.                       |
| `SpeechRecognitionReportSpeechAction`             | Return to `IDLE` + acknowledgment. (No longer dispatched by the service; kept as an RPC contract.) |

`_apply_wake_mode` (`reducer.py`) is the single mode→effect map, shared by audio detections and
Infrared-bound triggers: `INTENTS` arms the command listener (blue ring) when idle;
`QUICK_CHAT`/`CONVERSATION` dispatch `AssistantStartListeningAction` when idle (subject to the
`assistant_enabled` gate on the audio path); `STOP_TALKING` dispatches `AssistantStopTalkingAction`,
or — while the command window is armed — simply dismisses it. A wake detected *during* a quick-chat
session leaves `ASSISTANT_WAITING` intact: OpenWakeWord is not grammar-constrained and can still fire
there, and dropping to `IDLE` would disarm stage-1 for the rest of the session (the arming autorun
keys off `is_listening`, which has not changed, so it would never re-arm).

## Two-stage voice commands during a quick-chat session

A QUICK_CHAT wake ("hey quick question") starts an assistant session in which *every* utterance would
otherwise be answered by the LLM — including "turn on the lights", which a configured voice shortcut
already handles. Two stages avoid that:

- **Stage 1 (local, offline).** While the session listens, `status` is `ASSISTANT_WAITING` and the
  Vosk grammar is armed with the same expanded shortcut phrases the `INTENTS` window uses. A match
  runs the bound action and ends the session, so the turn never reaches the LLM.
- **Stage 2 (LLM).** The `commands_catalog` is exposed to the LLM as one generic
  `run_device_command(command_id)` tool, so a near-miss phrasing that fell through to the LLM can
  still trigger a shortcut. Unavailable on providers that don't support tools (`cerebras`, `ollama`,
  `ollama_onprem`); stage 1 still works there.

Two details are load-bearing:

- **The stop phrase rides along in the armed grammar** (`matching.stop_talking_triggers`). Vosk's
  grammar is whatever the *ongoing* recognition asks for and nothing else — its wake words are
  dropped while one is active, and `SpeechRecognitionMixin.report` never falls through to the wake
  mixin. Without folding the `STOP_TALKING` phrases in, arming stage-1 would take barge-in deaf for
  the whole session. Shortcuts are matched *first*, so a shortcut containing the stop phrase ("stop
  the music" against a "stop" trigger) still runs the shortcut.
- **Discarding the turn is not automatic.** The `InterruptionFrame` raised by
  `AssistantStopTalkingAction` cancels in-flight LLM/TTS but does *not* clear pipecat's user
  aggregation, and session teardown flushes it. The assistant subprocess's `StopTalkingOnSignal` sits
  downstream of STT and both resets the aggregator and swallows the late cloud-STT transcript.

Stage-1 is armed only for on-device quick-chat sessions: `_queue_chunk` drops remote (web/mobile) mic
audio, so Vosk could never hear such a session — hence the `assistant_session_audio_source` gate.

## Runtime & Setup

`init_service()` (`setup.py:661`) is the runtime hub and returns a `Subscriptions` list for teardown:

1. **Persistence** — `_register_persistence()` registers `wake_engines`, `assistant_enabled`,
   `conversation_end_phrases`, and the commands key.
2. **Bindable actions** — `register_default_bindable_actions()` + `register_shortcut_actions()`
   (`commands.py`) populate the catalog voice commands and Infrared bindings resolve against.
3. **Engines** — `EnginesManager()` (`engines_manager.py:75`) is the heart of the runtime.
4. **Autoruns** — `wake_menu_items` rebuilds the wake-up menu tree from
   `wake_engines`/`openwakeword_models`/model-status/infrared devices; `speech_recognition_command_
   items` rebuilds the Voice Shortcuts menu (warns + offers "Download Vosk" when the model is
   missing).
5. **Model pool seed** — scans OpenWakeWord's disk pool and dispatches
   `WakeWordSetAvailableModelsAction`/`WakeWordSetModelsStatusAction` (never in the reducer — no
   filesystem I/O there).
6. **Path matcher** — `register_path_menu_matcher('speech-recognition:settings', …)`.
7. **Event subscriptions** — bound-action-triggered, model download, model delete.

### Engine plugin / mixin model

Engines compose three abstraction layers so `EnginesManager` can drive any of them uniformly:

- `BaseSpeechRecognitionEngine` (`abstraction/base_class.py`) extends the shared
  `BackgroundRunningMixin`, owns the bounded `input_queue`, and on a failed `run()` disables the
  whole wake engine (`WakeEngineSetEnabledAction`) so the manager stops feeding it.
- `SpeechRecognitionMixin` adds command/end-phrase recognition (`activate_speech_recognition`,
  `speech_recognitions()` async generator).
- `WakeWordRecognitionMixin` adds trigger-list wake detection (`set_triggers`,
  `wake_word_recogntions()` yielding **trigger ids**, not phrases).

`VoskEngine` inherits **both** mixins (it is the speech engine and a wake engine);
`OpenWakeWordEngine` inherits only the wake mixin. To add an engine (e.g. Picovoice): subclass the
appropriate mixin(s), then register the instance in `EnginesManager._wake_engines` and add its name
to `WakeWordEngineName` — the manager's sync/monitor/cleanup loops pick it up automatically.

`EnginesManager` fans each system-mic `AudioReportSampleEvent` out to the speech engine plus every
enabled wake engine (`_queue_chunk`; remote-sourced audio with a non-empty `audio_source` is
ignored), keeps a per-engine `trigger id → (value, mode)` index so a detection resolves without a
store read, and per-mode debounces detections (`STOP_TALKING` is exempt). `_cleanup` cancels the
monitor tasks and stops each engine instance once.

### Lazy model loading (critical)

Both engines are designed to **start at boot without their models on disk** and self-heal when the
model is downloaded at runtime — an eager load would crash the engine and nothing reliably restarts
it. In Vosk (`vosk_engine.py:144` `_reconcile`, `:221` `_run`) the loop stays alive with
`recognizer=None`, drops audio while the model is missing, throttles reload attempts
(`_MODEL_RETRY_INTERVAL_SECONDS`), and builds the recognizer the moment the model appears.
OpenWakeWord (`openwakeword_engine.py:299` `set_triggers`) recomputes a *signature* of the enabled
stems that actually exist on disk, so a model that finishes downloading later changes the signature
and triggers a reload instead of committing to a partially-loaded set.

### Wake-phrase validation

Phrase editing (`wake_menu.py`) validates against the loaded Kaldi vocabulary via pure functions in
`wake_phrase_validation.py`: `validate_phrase` checks word count, character set, and vocabulary
membership (`model.vosk_model_find_word` — the model has no plaintext lexicon), and
`phrase_collisions` prevents a value colliding with another trigger on the same engine or a
conversation-end phrase. The model is Vosk's single loaded instance, surfaced via
`EnginesManager.wake_word_model()`.

## User Interface

- **Settings entries:** "Voice Shortcuts" under `SettingsCategory.ACCESSIBILITY` and "Wake Up"
  under `SettingsCategory.ASSISTANT` (`_register_static_menus`).
- **Wake-up menu tree (dumb UI):** `wake_menu.dispatch_wake_menus` builds a mode-first tree
  (Phrases → per-mode triggers, Silence, Engines → per-engine enable + Models) via
  `UpdateDynamicMenuAction`; `register_wake_handlers` wires the add/edit/remove trigger, Infrared
  binding, model download/upload/delete, and end-phrase handlers.
- **Voice Shortcuts menu:** lists each command; add/edit/remove via a `WebUIInputDescription` form
  (`_command_form`) with per-line utterance patterns (`pattern.py`, syntax help behind the ⓘ).
- **Notifications:** sticky radial-progress notification during OpenWakeWord model downloads
  (stable id so updates replace, not stack).
- **Path matcher:** `_speech_recognition_path_matcher` resolves both settings deep-links to the
  right dynamic menu.

## System / Hardware Integration

- **Microphone:** consumes `AudioReportSampleEvent` from the audio service (system mic only) — no
  direct hardware access here.
- **Vosk:** in-process Kaldi recognition on a single-worker `ThreadPoolExecutor`; `SetGrammar` is
  used on RPi (`IS_RPI`), a fresh recognizer elsewhere.
- **OpenWakeWord:** ONNX inference (onnxruntime) with optional Silero VAD and Speex noise
  suppression (native, Linux-only — silently off on dev hosts); models under
  `DATA_PATH/openwakeword/models`.
- **Mic buffer dumps:** WAV files under `DATA_PATH/wake_phrase_recordings`.

## Cross-Service Interactions

- **Assistant:** dispatches `AssistantStartListeningAction`/`AssistantStopTalkingAction` (with a
  `WakePhraseTriggerSource`); reads `state.assistant.selected_vosk_model` /
  `vosk_downloaded_models` and dispatches `AssistantDownloadVoskModelAction`.
- **Infrared:** reads `state.infrared.registered_devices`; per-mode wake bindables let a remote key
  trigger a mode (`SpeechRecognitionTriggerModeAction`, `commands.py:_trigger_mode`).
- **RGB ring:** listening indicator + acknowledgment sequences.
- **Notifications / core menu / bindable-actions & action registries:** commands resolve
  `action_keys` against the bindable-actions registry and dispatch the produced actions.

## Configuration

- Constants: `INTENTS_LISTENING_TIMEOUT_SECONDS` (10s, `constants.py`);
  `_DETECTION_DEBOUNCE_SECONDS`, `_MIC_BUFFER_DURATION_SECONDS` (`engines_manager.py`);
  `SPEECH_RECOGNITION_FRAME_RATE` (`ubo_app.constants`).
- Model locations: OpenWakeWord `DATA_PATH/openwakeword/models`; Vosk models via the assistant's
  `vosk_catalog` (`model_path_for`).
- Persistent keys: `speech_recognition:wake_engines`, `:assistant_enabled`,
  `:conversation_end_phrases`, `:commands` (plus legacy `:wake_slots` / Phase-1 keys read once on
  migration).
- No env vars or secrets owned here.

## Testing & Development Notes

Related tests (unit tier runs with `uv run poe test:unit`):

| Test                                              | Tier        | What it covers                                                  |
| ------------------------------------------------- | ----------- | ------------------------------------------------------------- |
| `tests/integration/test_services.py`              | Integration | `speech_recognition` registers; store snapshot matches.       |
| `tests/store/test_speech_recognition_wake_words.py`| Unit       | Detection `(engine, trigger_id)` → mode → `_apply_wake_mode` routing; assistant gate. |
| `tests/store/test_speech_recognition_commands.py` | Unit        | `DEFAULT_COMMANDS` seed + add/update/remove command reducer logic. |
| `tests/store/test_speech_recognition_grpc_roundtrip.py` | Unit  | Wake-word state survives `rebuild_object(build_message(state))` over gRPC. |
| `tests/store/test_wake_phrase_validation.py`      | Unit        | Word-count / char-set / vocabulary / collision checks (fake model). |
| `tests/store/test_vosk_engine_lazy_load.py`       | Unit        | Vosk engine starts before its model exists and self-heals on download. |
| `tests/store/test_vosk_catalog.py`                | Unit        | Curated Vosk model catalog + selector helpers.                |
| `tests/store/test_mic_buffer.py`                  | Unit        | Rolling `MicBuffer` window pruning + WAV dump (loaded by file path). |
| `tests/store/test_openwakeword_model_files.py`    | Unit        | `delete_model` filesystem guards (rejects traversal / helper models). |
| `tests/store/test_pattern_expansion.py`           | Unit        | `expand_pattern` grammar, dedup, and expansion cap.           |

**Maintenance when you change this service:**

- **State shape or menu items** (`SpeechRecognitionState`, wake-menu / command-menu output) →
  regenerate store/window snapshots (`docker … --override-store-snapshots
  --override-window-snapshots`); never hand-edit snapshot files. Seed/migrated trigger and command
  ids are deterministic on purpose — keep them so.
- **Reducer branches** (wake-mode routing, model lifecycle) → cover in
  `test_speech_recognition_wake_words.py` / `test_speech_recognition_commands.py`. Prefer a small
  pure-reducer unit test over the integration tier.
- **New engine / model handling** → add catalog + lazy-load coverage mirroring
  `test_vosk_engine_lazy_load.py` / `test_openwakeword_model_files.py`, and register the engine in
  `EnginesManager._wake_engines` + `WakeWordEngineName`.
- **Wake-phrase / collision logic** → `test_wake_phrase_validation.py`.
- **Pattern grammar** → `test_pattern_expansion.py`.
- **RPC contract changes** (new state fields / actions) → run `uv run poe proto` and add roundtrip
  coverage to `test_speech_recognition_grpc_roundtrip.py`.
- **Environment quirks:** real Vosk/OpenWakeWord inference and the mic pipeline run only where the
  native deps and hardware exist — `IS_RPI`-gated paths and model downloads are verified on-device;
  on dev hosts models are absent and VAD/Speex silently disabled.

To exercise manually: Settings → Assistant → Wake Up to edit phrases/engines/models, or Settings →
Accessibility → Voice Shortcuts to add a command; then speak a wake phrase and confirm the ring
indicator and the assistant/command effect.
</content>
</invoke>
