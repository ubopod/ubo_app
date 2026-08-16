# ubo-app assistant

A standalone subprocess that runs the device's **Pipecat** conversational
pipeline. It is the only place in ubo-app where STT, LLM, TTS and image
generation providers are instantiated: the core `090-assistant` service owns the
*state* (which providers are selected, which models are downloaded, which keys
exist), and this process turns that state into a running pipeline.

It talks to ubo-app exclusively over the gRPC store API (`ubo_bindings`) on
`localhost:50051` — it never imports `ubo_app`.

## Why it is a separate process

- **Dependency weight and isolation.** `pipecat-ai` with its provider extras,
  plus `vosk`, `piper-tts`, Kokoro and Moonshine, is a large and version-touchy
  dependency tree. It lives in its own virtualenv so it cannot constrain the
  core's.
- **A wider Python range.** The core pins `>=3.11,<3.12`; this package builds
  against `>=3.11,<3.14`.
- **Crash isolation.** A provider blowing up takes down a restartable
  subprocess, not the store.

Because it cannot import the core store package, a few values are **mirrored as
bare strings** in `constants.py` — `LIVE_PIPELINE_SOURCE_ID` (`'pipecat'`) and
`REQUEST_PIPELINE_SOURCE_ID` (`'assistant_request'`) must stay in sync with
`ubo_app.store.services.assistant`. A mismatch silently breaks chat routing
rather than raising.

## The two pipelines

```
        ┌─────────────── ubo-app core (gRPC :50051) ────────────────┐
        │  state.assistant  (selected providers, models, prompts)   │
        └────────▲─────────────────────────────────────┬───────────┘
                 │ AssistantReportAction               │ autorun / events
                 │ (source_id tags the producer)       │
        ┌────────┴─────────────────────────────────────▼───────────┐
        │  assistant subprocess (this package)                      │
        │                                                           │
        │  LIVE  'pipecat'            │  REQUEST  'assistant_request'│
        │  ──────────────────────     │  ──────────────────────────  │
        │  one long-lived pipeline    │  one short-lived pipeline    │
        │  UboInputTransport          │  per AssistantRunPipelineEvent│
        │    → STT → LLM → TTS        │  a contiguous STT/LLM/TTS    │
        │    → UboOutputTransport     │  sub-chain, output collected │
        │  barge-in, end-of-turn,     │  by GRPCTerminalCollector     │
        │  stop-talking, VAD          │                              │
        └───────────────────────────────────────────────────────────┘
```

**Live** (`main.py`) is the conversation the user hears: a `ParallelPipeline`
driven by a `WorkerRunner`, with audio arriving through `UboInputTransport` and
leaving through `UboOutputTransport`, wrapped in the turn-taking processors
described below.

**Request** (`request_handler.py`) serves external clients. It subscribes once
to `AssistantRunPipelineEvent` and builds an isolated, short-lived pipeline per
event via `pipeline_builder.build_request_pipeline`, reporting frames back
through `grpc_collector`. Tool-calling is deliberately not wired here yet — the
context aggregator is placed around the LLM so the structure is ready, but the
live `draw_image`/`get_image` tools need the live transports.

The client-facing contract for both — actions, events, result frames, enums — is
documented in the [service README](../README.md), not here.

## Module map

| Area | Modules |
| --- | --- |
| Entry point | `main.py` (`ubo-assistant` script) |
| Provider adapters | `ubo_stt.py`, `ubo_llm.py`, `ubo_tts.py`, `ubo_image_generator.py`, `switch.py` |
| Local engines | `vosk.py`, `piper.py`, `kokoro.py`, `moonshine.py`, `moonshine_cache.py`, `segmented_googlestt.py` |
| Provider one-offs | `venice_stt.py`, `venice_tts.py` |
| Transports | `ubo_input_transport.py`, `ubo_output_transport.py`, `grpc_collector.py`, `file_source.py` |
| Turn-taking | `barge_in.py`, `end_of_turn.py`, `stop_talking.py`, `stop_listening_on_bot_speech.py`, `silence_user_turn_stop.py` |
| Requests | `request_handler.py`, `request_providers.py`, `pipeline_builder.py` |
| Watchers | `system_prompt_watcher.py`, `policy_watcher.py` |
| Support | `constants.py`, `logging.py`, `error_notification.py`, `image_frame.py`, `tools.py`, `tts_voice.py`, `pipecat_debug.py` |

## Audio chunking (the one non-obvious constraint)

`MAX_AUDIO_CHUNK_BYTES` (8 KB) caps every emitted `AudioSample`. Pipecat hands
out ~0.5 s frames — roughly 48 KB at 48 kHz/16-bit — which overflow the heap of
memory-constrained clients; the ESP32 LVGL client has about 50 KB free, so
nanopb's decode `realloc` fails and TTS goes silent.

It is enforced **shared, not per-transport**, because every path that emits TTS
audio has to honour it. It previously lived in `ubo_output_transport` alone, so
the `grpc_collector` path — screen reader and one-shot requests — shipped whole
frames and satellites lost most of the utterance.

## Configuration

Provider credentials, model selections and defaults are injected as environment
variables by the service's `ubo_handle.py::binary_env_provider`, which resolves
them from the core's secrets store. This process reads `os.environ`; it never
reads the secrets file itself.

| Variable | Meaning | Default |
| --- | --- | --- |
| `UBO_ASSISTANT_LOG_LEVEL` | log level | `INFO` (invalid values warn and fall back) |
| `UBO_ASSISTANT_LOG_PATH` | log file path | `ubo-assistant.log` |
| `UBO_DATA_PATH` | model/data directory | platform user-data dir |

## Boundaries

- **Source of truth is the store.** Selections, downloads and credentials live
  in `state.assistant`; this process projects them into a pipeline.
- **No `ubo_app` imports.** Only `ubo_bindings`. See the `ubo_bindings` import
  rule in `.claude/rules/coding-style.md`.
- **MCP is not managed here.** Tools come from the separate
  [MCP gateway](../../090-mcp/ubo-service/README.md); this process is one of its
  clients.

## Tests

`tests/` runs under the sub-project's own venv:

```sh
poe --directory=ubo_app/services/090-assistant/ubo-service test    # fast, no network
```

It covers turn-taking
(`test_barge_in`, `test_end_of_turn`, `test_stop_talking`,
`test_silence_user_turn_stop`, `test_stop_listening_on_bot_speech`), engines
(`test_vosk`, `test_piper_tts`, `test_moonshine`, `test_lazy_local_tts`),
request orchestration (`test_request_orchestration`, `test_provider_*_roundtrip`)
and support behaviour (`test_logging`, `test_error_notification`,
`test_system_prompt_watcher`, `test_policy_watcher`).

`tests/provider_harness.py` backs the `providers`-marked tests — real TTS/STT/LLM
round-trips against whatever the secrets file configures. They are excluded from
`test` because they cost network and money; run them with
`poe … test:providers`, which CI does on the Pi pods.
