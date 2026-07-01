# Chat Service (`090-chat`)

## Overview

The chat service owns the on-device chat overlay: the conversation history, the chat session
lifecycle, and the bridge between the assistant pipeline (STT/LLM/TTS) and the rendered speech
bubbles. It holds the UI-logic representation of a conversation in Redux and lets the "dumb"
clients render it; it never touches audio bytes directly (those live in the audio service, keyed
by `audio_id`).

It loads in the `090-` application tier — it depends on the assistant (`075`) and audio (`000`)
slices being present, and it is a leaf consumer rather than a hardware/system provider.

> **No `setup.py`.** Unlike most services, all runtime wiring lives in `ubo_handle.py`'s `setup`
> callback (see below). There is no `setup.py`/`init_service()` split; the reducer is registered
> and the subscriptions are wired inline.

For the action/event/store model, see
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## Files

| Path            | Purpose                                                                                  |
| --------------- | ---------------------------------------------------------------------------------------- |
| `ubo_handle.py` | Registration **and** all runtime: the assistant↔chat voice handler, idle-dismiss loop, test-only echo handler, optional menu item. |
| `reducer.py`    | Pure reducer for the `chat` slice; session/message mutations + cross-service activity gating. |

Store types: [`ubo_app/store/services/chat.py`](../../store/services/chat.py).

## State

Slice: `state.chat` — [`ChatState`](../../store/services/chat.py):

| Field               | Type                     | Meaning                                                              |
| ------------------- | ------------------------ | ------------------------------------------------------------------- |
| `messages`          | `Sequence[ChatMessage]`  | Conversation history (trimmed to 200 messages).                     |
| `session_id`        | `str`                    | Current session id (hex).                                           |
| `is_active`         | `bool`                   | Whether the chat overlay is open.                                   |
| `last_activity_time`| `float \| None`          | Timestamp of last chat write / TTS playback-done; drives idle dismiss. |
| `is_audio_playing`  | `bool`                   | True while pipecat TTS is *actually* being played out (gates dismiss). |
| `messages_revision` | `int`                    | Monotonic counter bumped on every `messages` mutation (O(1) view selector). |

`ChatMessage` carries `role`, `id`, `kind` (`text`/`audio`), `text`, `audio_id`, `waveform`,
`is_playing`, `timestamp`. Audio bytes are **never** stored here — `audio_data` is a typed
placeholder a unit test pins to `b''`.

## Actions & Events

Events are emitted **only from the reducer**; the handlers in `ubo_handle.py` subscribe to them.

| Action (in)                    | Reducer result                                                          |
| ------------------------------ | ---------------------------------------------------------------------- |
| `ChatStartSessionAction`       | Resets to a fresh session; → `StackPushChatAction` + `ChatSessionStartedEvent`. |
| `ChatEndSessionAction`         | Deactivates; → `StackPopChatAction` + `ChatSessionEndedEvent`.         |
| `ChatAddMessageAction`         | Appends a message (fills a deterministic waveform for audio bubbles).  |
| `ChatSendUserMessageAction`    | Appends a USER bubble; → `ChatUserMessageSentEvent` (the responder seam). |
| `ChatAppendToMessageAction`    | Appends a streamed chunk (LLM delta path).                            |
| `ChatSetMessageTextAction`     | Replaces a message's text wholesale (cumulative STT path).            |
| `ChatToggleAudioPlaybackAction`| Toggles one bubble's `is_playing`; → `ChatAudioPlaybackToggledEvent`. |
| `ChatClearAction`              | Clears all messages.                                                  |
| `AudioPlayAudioSequenceAction`*| (`ASSISTANT_LIVE` only) sets `is_audio_playing=True`.                 |
| `AudioPlaybackDoneAction`*     | (`ASSISTANT_LIVE` only) clears `is_audio_playing`, re-anchors `last_activity_time`. |

\* Cross-service actions the chat reducer observes but doesn't own — the audio service's
playback-done is the authoritative "speaker has gone quiet" signal.

## Runtime & Setup

`setup()` in `ubo_handle.py:424` registers the reducer, then wires runtime pieces directly:

- **Voice handler** — `_register_voice_handler()` (`ubo_handle.py:214`) is the real
  assistant↔chat bridge. An `@store.autorun` on `state.assistant.is_listening` opens/holds the
  session; `AssistantHandleReportEvent` (filtered to `LIVE_PIPELINE_SOURCE_ID`) routes STT frames
  (`ChatSetMessageTextAction`, cumulative) and LLM frames (`ChatAppendToMessageAction`, delta) into
  bubbles; `ChatSessionEndedEvent` stops the assistant on the Back-button path.
- **Idle dismiss** — a `create_task(_dismiss_loop())` polls `last_activity_time` every
  `_DISMISS_POLL_SECONDS` and dispatches `ChatEndSessionAction` once idle past
  `_DISMISS_DELAY_SECONDS`, unless listening / `is_audio_playing` / the post-turn
  `_AWAITING_RESPONSE_TIMEOUT_SECONDS` hold say otherwise (`_should_dismiss`, `ubo_handle.py:96`).
  Runtime turn state lives in a module-level `_VoiceState` dataclass (per the no-globals rule).
- **Echo handler** — `_register_echo_handler()` is **test-only** scaffolding (gated by
  `IS_TEST_ENV`) that echoes `ChatUserMessageSentEvent` back as an assistant reply; it must not run
  alongside a real responder.
- **Menu item** — `_register_chat_menu_item()` (Settings → Assistant → "Chat") exists but is
  disabled (`show_chat_menu_item = False`); chat opens reactively via the voice handler.

The setup returns the combined unsubscribe/cancel list (autorun teardown, event unsubs, dismiss
cancel) for clean teardown.

## User Interface

- **Chat overlay:** pushed via `StackPushChatAction` (dumb-UI — clients render the resolved
  `ChatBubbleData` computed from `ChatMessage`, never the raw message).
- **No standing menu entry** by default (the Settings → Assistant item is flag-gated off).

## Cross-Service Interactions

- **Assistant (`075-assistant`):** reads `state.assistant.is_listening`; consumes
  `AssistantHandleReportEvent`; dispatches `AssistantStopListeningAction`/`AssistantStopTalkingAction`.
- **Audio (`000-audio`):** observes `AudioPlayAudioSequenceAction` / `AudioPlaybackDoneAction`
  (`AudioSequenceSource.ASSISTANT_LIVE`) to gate dismiss on real playback.
- **Core:** `StackPushChatAction` / `StackPopChatAction`.

## Configuration

No env vars or secrets. Tunables are module constants in `ubo_handle.py`
(`_DISMISS_DELAY_SECONDS`, `_DISMISS_POLL_SECONDS`, `_AWAITING_RESPONSE_TIMEOUT_SECONDS`) and
`reducer.py` (`_CHAT_HISTORY_MAX_MESSAGES`, `_WAVEFORM_BAR_COUNT`).

## Testing & Development Notes

| Test                                     | Tier        | What it covers                                                     |
| ---------------------------------------- | ----------- | ----------------------------------------------------------------- |
| `tests/store/test_chat_reducer.py`       | Unit        | Session/message reducer branches, trimming, audio-playback gating (~23 cases). |
| `tests/store/test_chat_voice_handler.py` | Unit        | The assistant→chat bridge: listening edges, STT/LLM routing, dismiss decisions (~19 cases). |
| `tests/flows/test_chat_widget.py`        | Flow (E2E)  | Chat widget window-snapshot harness (Docker/on-device).           |
| `tests/integration/test_services.py`     | Integration | Asserts the `chat` service registers and the store snapshot matches. |

**Maintenance when you change this service:**

- **State shape** (`ChatState`/`ChatMessage`) or the pushed chat view → regenerate store/window
  snapshots (never hand-edit them); this feeds `test_services.py` and `test_chat_widget.py`.
- **Reducer branch** (new action/event, activity gating) → add a case to
  `tests/store/test_chat_reducer.py`.
- **Voice-handler logic** (listening edges, frame routing, dismiss timing) → cover it in
  `tests/store/test_chat_voice_handler.py`; prefer this pure-ish unit test over the flow harness.
- **Invariants to preserve:** events only from the reducer; audio bytes never enter `ChatState`
  (`audio_data` stays `b''`); `is_audio_playing` gates dismiss so a session can't close
  mid-utterance; `_register_echo_handler` stays behind `IS_TEST_ENV` so it never races the real
  responder.

To exercise manually: trigger the assistant (push-to-talk / wake word), confirm the chat overlay
opens, STT/LLM text streams into bubbles, and the overlay auto-dismisses a few seconds after the
reply's audio finishes.
