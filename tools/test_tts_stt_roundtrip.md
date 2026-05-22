# Assistant e2e test — `test_tts_stt_roundtrip.py`

A disposable end-to-end test for the assistant's programmatic gRPC pipeline. It
boots the app, waits for the assistant service, and exercises every pipeline
shape over the gRPC API:

- `tts-stt-roundtrip` — synthesize a sentence, transcribe it back, fuzzy-match.
- `llm-<provider>` — LLM completion, provider selected per-request.
- `llm-tts-<provider>` — `text → LLM → TTS`; the LLM echoes a fixed sentence and
  the spoken output is fed back through STT and fuzzy-matched.
- `stt-llm-<provider>` — `STT → LLM → text`, input audio TTS-generated.

## Running it (manual, on a dev machine)

```sh
uv run python tools/test_tts_stt_roundtrip.py
```

It needs the STT/TTS/LLM providers actually set up (local providers need their
models downloaded; cloud providers need API keys). A scenario whose provider is
**not** set up is **SKIPPED with an explicit message, not failed** — so the test
degrades gracefully on a partially-configured machine. Edit `TTS_PROVIDER` /
`STT_PROVIDER` / `LLM_PROVIDERS` at the top of the script to match what is
available. Exit code: `0` = nothing failed (skips are fine), `1` = a failure.

## CI/CD integration — deferred (test debt)

This test is **intentionally not in CI yet.** The CI/test environment has no
STT/TTS/LLM providers, and provisioning them is slow and heavy — tracked here as
test debt to pick up later.

When it is integrated, the intended shape:

1. **Promote it to a gated pytest e2e** — move the scenarios into
   `tests/flows/test_assistant_e2e.py` with an `e2e` marker (registered in the
   root `pyproject.toml`). The test **auto-skips with a clear reason** when
   prerequisites are absent, so a bare `uv run poe test` never fails or pays a
   cost in an unprovisioned environment. Reuse the boot / round-trip machinery
   from this script. Keep the per-scenario capability skipping.

2. **Local tier runs in a dedicated CI job** — nightly or pre-merge-to-`main`
   (not every push — app boot takes minutes). It runs the keyless, deterministic
   providers:
   - **Vosk (STT) + Piper (TTS)** — need model *files* only. Download once,
     restore from an `actions/cache` keyed on model version.
   - **Ollama (LLM)** — install the **Ollama binary natively on the runner**
     (`curl -fsSL https://ollama.com/install.sh | sh`), *not* the
     `ollama/ollama` Docker image (the image bundles GPU runtimes that are dead
     weight on a CPU runner, ~1-3 GB). Pull a small model —
     `liquidai/lfm2.5-350m` (≈379 MB, in `ollama_catalog.py`). Cache `~/.ollama`.
     The assistant reaches Ollama at `localhost:11434` regardless. Pin the model
     per-request via `AssistantRunPipelineAction.llm_model` so the test does not
     depend on `selected_models` state.

3. **Cloud LLM tier is opt-in** — OpenAI/Anthropic etc. run only in a manual or
   release job that holds the key secrets, and their failures should alert
   rather than gate (a provider outage is not our regression).

4. **Test ubo's docker service separately.** Do *not* drive Ollama through the
   docker service (`DockerImageFetchAction`/`DockerImageRunAction`) inside this
   e2e — an image pull in the critical path adds flake and makes a failure
   ambiguous ("assistant broke?" vs "docker-fetch broke?"). The `080-docker`
   service has its own reducer/composition logic; give it its own test.

5. **Pair with fast unit tests.** The request feature (`pipeline_builder`,
   `grpc_collector`, `request_handler`, `request_providers` in the assistant
   `ubo-service`) is logic that tests fine with fakes — those belong in the
   default CI run. With that layer solid, this e2e is purely the "real providers
   actually work" smoke layer and can stay gated/infrequent.

### Risks to validate before committing to a stock runner
- **Disk** — the assistant `ubo-service` venv (`pipecat-ai` with every extra +
  `vosk` + `piper-tts` + whisker) is itself multiple GB; plus models. A stock
  `ubuntu-latest` runner (~14 GB usable) may be tight — measure first; a
  disk-cleanup step or a larger runner may be needed.
- **Stability** — the real flake risk is booting the whole app + the heavy
  assistant subprocess on a slow runner, not Ollama. Use generous boot/retry
  budgets and cache aggressively.
