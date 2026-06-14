# Assistant Service — gRPC API

The assistant service exposes speech-to-text (STT), text-to-speech (TTS), large-language-model
(LLM) completions, and live voice conversations to external clients over gRPC.

The assistant is reached through the
app-wide **`StoreService`** (`ubo_app/rpc/proto/store/v1/store.proto`). The interaction model
is *action-in / event-out*:

- **Request** — dispatch an assistant `Action` via `StoreService.DispatchAction`.
- **Result** — subscribe to `AssistantHandleReportEvent` via `StoreService.SubscribeEvent`;
  each event carries one assistance frame (text / audio / image / error), correlated by
  `session_id` and terminated by `is_last_frame`.

Events are emitted **only** by reducers — a remote client can never dispatch an event, only an
action. The reducer maps your `AssistantRunPipelineAction` (or a shortcut) onto an internal
`AssistantRunPipelineEvent`, the assistant subprocess runs the pipeline, and its output is
reported back to clients as `AssistantHandleReportEvent`s.

## Connecting

The gRPC server listens on `127.0.0.1:50051` by default. Override via environment variables:

| Variable                  | Default     | Meaning                       |
| ------------------------- | ----------- | ----------------------------- |
| `UBO_GRPC_LISTEN_ADDRESS` | `127.0.0.1` | Bind address (loopback-only)  |
| `UBO_GRPC_LISTEN_PORT`    | `50051`     | Bind port                     |

There is **no authentication** on the gRPC endpoint — it is bound to loopback by default and is
expected to stay behind the app boundary. (Browser clients reach it through the Envoy gRPC-web
bridge on port `50052`; that path is out of scope for this document.)

The in-repo Python client is `UboRPCClient` (`ubo_app/rpc/ubo_bindings/client.py`). The
`ubo_bindings` package is generated from the proto definitions — run `uv run poe proto` after any
change to store actions/events.

```python
from ubo_bindings.client import UboRPCClient

client = UboRPCClient('localhost', 50051)
# ... dispatch actions / subscribe to events ...
client.close()
```

> All assistant message types live in `ubo_bindings.ubo.v1`. The canonical Python-side
> definitions (with full docstrings) are in `ubo_app/store/services/assistant.py`.

## Core concepts

- **`session_id`** — a client-chosen correlation id. Set it on every request action and filter
  incoming report frames by it. Live (wake-phrase / keypad) output uses an empty `session_id`.
- **`stages`** — a programmatic pipeline runs a **contiguous sub-chain** of `[STT, LLM, TTS]`,
  in that order. Valid examples: `[STT]`, `[LLM]`, `[TTS]`, `[STT, LLM]`, `[LLM, TTS]`,
  `[STT, LLM, TTS]`. Non-contiguous chains (e.g. `[STT, TTS]`) are rejected.
- **Provider resolution** — provider/model fields left unset on the request fall back to the
  user's current selection in `AssistantState` (see *Configuration & providers*).
- **Audio format** — input and output audio is **16 kHz, mono, signed 16-bit little-endian
  PCM**. The request handler chunks input into 640-byte (20 ms) frames and appends ~1.5 s of
  trailing silence so streaming STT engines finalize.
- **Termination** — the last frame of a response has `is_last_frame = True`. `index` increases
  monotonically within a response.

## Request pipeline (primary use case)

### `AssistantRunPipelineAction`

The canonical request. Dispatch it as `Action(assistant_run_pipeline_action=...)`.

| Field           | Type                          | Notes                                                            |
| --------------- | ----------------------------- | ---------------------------------------------------------------- |
| `session_id`    | `str`                         | Correlation id (required).                                       |
| `stages`        | `list[AssistantPipelineStage]`| Contiguous sub-chain of `[STT, LLM, TTS]`.                       |
| `audio`         | `bytes`                       | Input PCM for an STT-first pipeline. Default `b''`.              |
| `text`          | `str`                         | Input text for an LLM- or TTS-first pipeline. Default `''`.      |
| `sample_rate`   | `int`                         | Default `16000`.                                                 |
| `num_channels`  | `int`                         | Default `1`.                                                     |
| `stt_provider`  | `AssistantSttName` (optional) | Unset → user's selected STT.                                     |
| `llm_provider`  | `AssistantLlmName` (optional) | Unset → user's selected LLM.                                     |
| `tts_provider`  | `AssistantTtsName` (optional) | Unset → user's selected TTS.                                     |
| `llm_model`     | `str` (optional)              | Unset → selected model for that LLM.                             |
| `system_prompt` | `str` (optional)              | LLM system prompt.                                               |
| `enable_tools`  | `bool`                        | Allow MCP tool calls during the LLM stage. Default `False`.     |

### Shortcut actions

Convenience wrappers that the reducer funnels into the same canonical pipeline:

- `AssistantTranscribeAction` — STT-only. Fields: `audio`, `session_id`, `sample_rate` (16000),
  `num_channels` (1), `stt_provider` (optional).
- `AssistantSynthesizeAction` — TTS-only. Fields: `text`, `session_id`, `tts_provider` (optional).
- `AssistantCompleteAction` — LLM-only. Fields: `text`, `session_id`, `llm_provider` (optional),
  `system_prompt` (optional), `enable_tools` (default `False`).

### Worked example — transcribe audio (STT-only)

Subscribe **before** dispatching so no frames are missed, filter by `session_id`, and collect
text until `is_last_frame`:

```python
import asyncio

import betterproto
from ubo_bindings.client import UboRPCClient
from ubo_bindings.ubo.v1 import (
    Action,
    AssistantPipelineStage,
    AssistantRunPipelineAction,
    AssistantHandleReportEvent,
    Event,
)


async def transcribe(pcm_16k_mono: bytes) -> str:
    client = UboRPCClient('localhost', 50051)
    session_id = 'demo-stt-1'
    done = asyncio.Event()
    transcript: list[str] = []

    def on_event(event: Event) -> None:
        report = event.assistant_handle_report_event
        if not report:
            return
        which, frame = betterproto.which_one_of(report.data, 'acceptable_assistance_frame')
        if frame.session_id != session_id:
            return
        if which == 'assistance_text_frame':
            transcript.append(frame.text)
        elif which == 'assistance_error_frame':
            transcript.append(f'[error] {frame.error}')
        if frame.is_last_frame:
            done.set()

    unsubscribe = client.subscribe_event(
        event_type=Event(assistant_handle_report_event=AssistantHandleReportEvent()),
        callback=on_event,
    )

    client.dispatch(
        action=Action(
            assistant_run_pipeline_action=AssistantRunPipelineAction(
                session_id=session_id,
                stages=[AssistantPipelineStage.STT],
                audio=pcm_16k_mono,
            ),
        ),
    )

    await done.wait()
    unsubscribe()
    client.close()
    return ''.join(transcript)
```

Other pipelines reuse the same loop — only the action changes:

```python
# LLM-only: text → text
Action(assistant_run_pipeline_action=AssistantRunPipelineAction(
    session_id=session_id, stages=[AssistantPipelineStage.LLM], text='Tell me a joke.'))

# TTS-only: text → audio (read AssistanceAudioFrame instead of text)
Action(assistant_run_pipeline_action=AssistantRunPipelineAction(
    session_id=session_id, stages=[AssistantPipelineStage.TTS], text='Hello there.'))

# Full STT → LLM → TTS: audio in, audio out
Action(assistant_run_pipeline_action=AssistantRunPipelineAction(
    session_id=session_id,
    stages=[AssistantPipelineStage.STT, AssistantPipelineStage.LLM, AssistantPipelineStage.TTS],
    audio=pcm_16k_mono,
    enable_tools=False))
```

## Result frames

Every result arrives as an `AssistantHandleReportEvent` whose `data` is one of the frames below
(a protobuf `oneof` — use `betterproto.which_one_of(report.data, 'acceptable_assistance_frame')`).
All frames share `is_last_frame`, `timestamp`, `id`, `index`, and `session_id`.

| Frame                   | Extra fields                                   | Produced by         |
| ----------------------- | ---------------------------------------------- | ------------------- |
| `AssistanceTextFrame`   | `text`, `source` (`AssistantPipelineStage`)    | STT and LLM stages  |
| `AssistanceAudioFrame`  | `audio` (`AudioSample`: `data`, `channels`, `rate`, `width`) | TTS stage |
| `AssistanceImageFrame`  | `image` (bytes), `width`, `height`, `format`, `metadata` | image generation |
| `AssistanceErrorFrame`  | `error` (str)                                  | any stage on failure|

`AssistanceTextFrame.source` is the discriminator between a transcription (`STT`) and a model
reply (`LLM`) — route on the enum, never by parsing the text.

`source_id` on the event identifies the originating pipeline: `assistant_request` for
programmatic requests, `pipecat` for live conversation output.

## Live conversation control

Drive a hands-free voice session (the same flow used by the wake phrase / keypad on-device):

- `AssistantStartListeningAction` — begin a listening session.
  - `audio_source` (`str`, default `''`) — which mic feeds the session: empty = on-device system
    mic; a remote client sets a unique id and must tag its `AudioReportSampleAction`s with the
    same value.
  - `source` (optional) — structured trigger metadata; pipeline behaviour is selected per-source
    via `AssistantState.policies`.
- `AssistantStopListeningAction` — end the session. Optional `reason`.
- `AssistantToggleListeningAction` — toggle; forwards `source` / `audio_source` to whichever
  direction it resolves to.
- `AssistantStopTalkingAction` — silence in-flight TTS/LLM **without** starting a new listening
  session.

Live output is delivered through the same `AssistantHandleReportEvent` stream, but with an
**empty `session_id`** and `source_id = 'pipecat'`.

## Configuration & providers

Per-request providers are optional; when unset, the pipeline uses the user's current selection.
Set those selections with:

- `AssistantSetIsActiveAction(is_active: bool)` — enable/disable the assistant.
- `AssistantSetSelectedSTTAction(stt_name: AssistantSttName)`
- `AssistantSetSelectedLLMAction(llm_name: AssistantLlmName)`
- `AssistantSetSelectedTTSAction(tts_name: AssistantTtsName)`
- `AssistantSetSelectedImageGeneratorAction(image_generator_name: AssistantImageGeneratorName)`
- `AssistantSetSelectedModelAction(model: str, llm_name: AssistantLlmName | None = None)`

Provider API keys are resolved server-side from the secrets store; clients don't pass credentials.

## MCP server management

The LLM stage can call tools from registered MCP servers (when `enable_tools=True`):

- `AssistantAddMcpServerAction(name, type, config)` — `config` is `StdioMcpConfig` or
  `SseMcpConfig` (a protobuf `oneof`).
- `AssistantToggleMcpServerAction(server_id)` — enable/disable.
- `AssistantDeleteMcpServerAction(server_id)` — remove.
- `AssistantSyncMcpServersAction()` — reload server configs from the filesystem.

## Enums reference

`AssistantPipelineStage`: `STT`, `LLM`, `TTS`.

`AssistantSttName`: `VOSK`, `GOOGLE_SEGMENTED`, `GOOGLE`, `OPENAI`, `DEEPGRAM`, `ASSEMBLYAI`,
`VENICE`.

`AssistantLlmName`: `OLLAMA`, `OLLAMA_ONPREM`, `GOOGLE`, `OPENAI`, `GROK`, `CEREBRAS`,
`ANTHROPIC`, `QWEN`, `DEEPSEEK`, `OPENROUTER`, `MISTRAL`, `VENICE`, `GENERIC`.

`AssistantTtsName`: `PIPER`, `KOKORO`, `GOOGLE`, `OPENAI`, `ELEVENLABS`, `RIME`, `VENICE`.

`AssistantImageGeneratorName`: `GOOGLE`, `OPENAI`.

## Notes & limits

- **Concurrency** — the request handler processes at most **3** concurrent pipeline requests;
  excess requests queue behind a semaphore.
- **Timeouts** — STT finalization waits up to 15 s; an idle pipeline times out after 120 s.
- **Loopback-only / no auth** — keep the endpoint local or front it with your own auth layer.
- **Generated bindings** — `ubo_bindings` is regenerated by `uv run poe proto`; the message
  field names follow betterproto's snake_case convention (`assistant_run_pipeline_action`,
  `assistant_handle_report_event`, …).
