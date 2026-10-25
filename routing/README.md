# routing

A local assistant that sends each prompt to the right Gemma model. For every prompt it:

1. **Classifies** it into a domain (`medical`, `car` or `general`) in a few hundred milliseconds.
2. **Answers** it with that domain's model, using a system prompt built from that domain's history (`profiles/<domain>.md`).

Everything runs on-device (developed on a Raspberry Pi 5 with 16 GB of RAM). There are two backends: Ollama (local, or on another machine) and LiteRT-LM. Medical questions can also be sent to an Ollama server on another machine with `--remote-ollama-url`, while everything else stays local (see [Remote medical route](#remote-medical-route)).

## Quick start

```sh
# Ollama
ollama pull embeddinggemma:300m
ollama pull gemma4:e2b
ollama pull gemma4:12b
python3 router.py --backend ollama

# LiteRT-LM
python3 -m venv .venv
.venv/bin/pip install litert-lm-api huggingface_hub
.venv/bin/hf download litert-community/embeddinggemma-2-text-270m-litert-lm embeddinggemma-2-text-270m.litertlm --local-dir ~/models
.venv/bin/hf download litert-community/gemma-4-E2B-it-litert-lm gemma-4-E2B-it.litertlm --local-dir ~/models
.venv/bin/hf download litert-community/gemma-4-12B-it-litert-lm gemma-4-12B-it.litertlm --local-dir ~/models
.venv/bin/python router.py
```

Type a prompt at `Ask`. An empty line quits.

| Option | Default | Meaning |
|---|---|---|
| `--backend {ollama,litert}` | `litert` | Which runtime to use |
| `--ollama-url URL` | `http://localhost:11434` | Use an Ollama server on another device for every route |
| `--remote-ollama-url URL` | none | Answer medical questions on this Ollama server, with either backend |
| `--models-dir DIR` | `~/models` | Where the `.litertlm` files are |
| `--show-scores` | off | Print every domain's similarity score |

## Models

| Role | Remote Ollama | Ollama | LiteRT-LM | Size on disk (LiteRT) |
|---|---|---|---|---|
| Classifier, stage 1 (embeddings) | | `embeddinggemma:300m` | `embeddinggemma-2-text-270m.litertlm` | 165 MB |
| Classifier, stage 2 (tiebreak) | | `gemma4:e2b` | `gemma-4-E2B-it.litertlm` | 2.6 GB |
| Medical | `medgemma-1.5:4b` | `medgemma:4b` | `gemma-4-12B-it.litertlm` | 6.9 GB |
| Car | | `gemma4:e2b` | `gemma-4-E2B-it.litertlm` | |
| General | | `gemma4:e2b` | `gemma-4-E2B-it.litertlm` | |

The remote model is used only with `--remote-ollama-url`. Otherwise, or while the remote is down, the medical route uses its local model.

Medical questions go to a medical or large model because mistakes matter most there. Car and general questions are mostly lookups in the history or everyday chat, so the fast E2B is enough. Routes that share a model also share one loaded copy of it.

With LiteRT, if a route's `.litertlm` file isn't in `--models-dir`, the router prints a warning and answers with the general route's model instead. The route's profile is still used. For example, until `gemma-4-12B-it.litertlm` is downloaded, the E2B answers medical questions.

Each route's model is just an entry in `ROUTES`, so a route can use a different model, the same model with a different profile, or a specialised one. For example, the medical route's `litert` entry could point at a MedGemma `.litertlm` file.

## Remote medical route

```sh
# On the remote machine
ollama pull medgemma-1.5:4b
OLLAMA_HOST=0.0.0.0 ollama serve

# On the Pi
.venv/bin/python router.py --remote-ollama-url http://192.168.1.50:11434
```

- Medical answers go to `medgemma-1.5:4b` on the remote, with either backend. Classification and the car and general answers stay on the local backend.
- A route opts in with a `"remote"` entry in its `model` dict. Any route can have one.
- Remote models are called through `/api/chat`, so Ollama applies the model's own chat template. MedGemma is based on Gemma 3 and doesn't use Gemma 4's `<|turn>` format.
- Remote models don't count against the Pi's `RAM_BUDGET_GB`, so medical questions no longer unload the local E2B.
- At startup the router warns if the remote can't be reached or doesn't have the model.
- Before each medical answer it checks the remote (3 s timeout). If the remote is down, or fails mid-answer, it prints a note and answers with the route's local model and the same profile:

```
[route] medical 0.86 (margin 0.07) in 204 ms
[http://192.168.1.50:11434 is unreachable; answering locally]
[gemma-4-12B-it.litertlm]
```

The medical profile and your questions travel to the remote over plain HTTP. Keep the remote on your own network or a VPN such as Tailscale.

## How classification works

Classification has to be fast. Generating text with an LLM costs seconds, while one embedding takes milliseconds, so the router tries embeddings first and only falls back to an LLM when they're unsure.

**Stage 1: embedding nearest-centroid** (usually all that's needed)

- Each domain in `ROUTES` has 10–12 example prompts.
- At startup the examples are embedded and averaged into one unit vector per domain (a centroid).
  - The centroids are cached in `centroids.json`, keyed on a hash of the examples and the embedding model.
  - Editing the examples or switching backend recomputes them automatically, since each backend uses a different embedding model.
- Each prompt gets one embedding call, then a cosine similarity against each centroid.
- Every text gets EmbeddingGemma's task prefix, `task: classification | query: `, which helps it produce embeddings suited to classification.
- The top domain wins if its score is at least `MIN_SCORE` (0.45) and it beats the runner-up by at least `MIN_MARGIN` (0.05).

**Stage 2: LLM tiebreak** (only when stage 1 is unsure)

- E2B gets a short raw Gemma 4 prompt that lists the domains and their descriptions.
- Its reply is prefilled with `Category:`, capped at 6 tokens and stopped at the first newline, with temperature 0.
- An unknown label falls back to `general`.

Every prompt prints how it was routed:

```
[route] car 0.73 (margin 0.25) in 369 ms
[route] car by tiebreak in 2666 ms (embeddings unsure: 0.64, margin 0.00, 338 ms)
```

### Measured on the Pi 5

| Prompt | Route | Decided by | Time |
|---|---|---|---|
| tyres are making a humming noise on the motorway | car | embeddings | 340 ms (8.5 s on first use, while the model loads) |
| write a haiku about autumn | general | embeddings | 338 ms |
| what oil does my car take? | car | embeddings | 369 ms |
| what was my last cholesterol reading? | medical | embeddings | 373 ms |
| my back hurts when I drive | car | tiebreak | 2.7 s |

The LiteRT embedding step is a little faster, at about 200–250 ms per prompt. Its scores sit closer together, though: margins of 0.07–0.10 on clear prompts, against 0.19–0.26 with Ollama. If LiteRT routes prompts wrongly or uses the tiebreak too often, adjust `MIN_SCORE` and `MIN_MARGIN`, or add more examples.

## Answering

- The system turn holds today's date (so the model can work out what's due) and the domain's profile. The `general` route has no profile.
- The prompt is sent raw, in Gemma 4's `<|turn>` format, and the answer is streamed to the terminal.
- The 12B opens every answer with an empty `<|channel>thought<channel|>` block, even with thinking off, so it's stripped from the output.
  - It can't be avoided by putting that empty block in the prompt instead: that makes the E2B actually start thinking.

The files in `profiles/` hold placeholder histories. Replace them with real details. They're plain text and become the system prompt verbatim.

## Memory management

Not every model fits in 16 GB at once. On this Pi:

| Model | Real RAM use | Size Ollama reports |
|---|---|---|
| `gemma4:12b` | ~9.6 GB | 1.4 GB |
| `gemma4:e2b` | ~5.8 GB | 0.4 GB |

Ollama counts only part of its memory-mapped model files, so it believes both fit and loads them together. That ran the Pi out of memory and forced a reboot. To stop that happening:

- **`make_room()`** runs before any model is loaded. It unloads others, biggest first, until the new one fits in `RAM_BUDGET_GB` (12 GB).
  - It uses the measured sizes in `MODEL_RAM_GB`.
  - It works on both backends: Ollama models are unloaded with `keep_alive: 0`, LiteRT engines with `close()`.
  - Models missing from the table are assumed to be 6 GB.
- **`KEEP_ALIVE`** is 30 minutes, not forever. Otherwise a loaded 12B would keep about 10 GB after the router exits.

As a result, switching between the medical route and the others reloads a model. Each switch prints a line like `[memory] unloading gemma4:e2b to fit gemma4:12b`. A cold load of the 12B took about 2 minutes on the Pi. To avoid that:

- use a smaller medical model, such as a 4B MedGemma, or
- run the medical model on another machine with `--remote-ollama-url`.

If you add a model, measure its real RAM use first (`free -m` before and after loading it) and add it to `MODEL_RAM_GB`.

## Adding a domain

1. Add an entry to `ROUTES` in `router.py` with:
   - a one-line `description` (used by the tiebreak),
   - a `model` for each backend,
   - a `profile` path, or `None`,
   - 10–20 varied `examples`.
2. Create the profile file in `profiles/`.
3. Run with `--show-scores` and try prompts on the borders between domains. The centroids are recomputed automatically on the next start.

## Files

| Path | Contents |
|---|---|
| `router.py` | Routing, both backends and the REPL |
| `profiles/medical.md`, `profiles/car.md` | Per-domain history, used as the system prompt |
| `centroids.json` | Cached domain centroids, generated automatically and safe to delete |
| `.venv/` | Python environment for the LiteRT backend |
