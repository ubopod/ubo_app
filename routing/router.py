import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

# "ollama" or "litert"; override with --backend.
BACKEND = "litert"
# Ollama server; override with --ollama-url to use one on another device.
OLLAMA_URL = "http://localhost:11434"
# Ollama server for routes with a "remote" model; set with --remote-ollama-url.
# None answers every route locally.
#REMOTE_OLLAMA_URL = None
REMOTE_OLLAMA_URL = "http://192.168.1.45:9379"
# True never answers a remote route locally: if the remote is unset or down,
# the prompt fails instead. Override with --remote-only.
REMOTE_ONLY = False
# Where the .litertlm files live; override with --models-dir.
MODELS_DIR = os.path.expanduser("~/models")
HERE = os.path.dirname(os.path.abspath(__file__))
CENTROIDS_PATH = os.path.join(HERE, "centroids.json")

# Embedding model per backend: Ollama has EmbeddingGemma 1, LiteRT-LM EmbeddingGemma 2.
EMBED_MODEL = {
        "ollama": "embeddinggemma:300m",
        "litert": "embeddinggemma-2-text-270m.litertlm",
        }
# EmbeddingGemma's prompt for classification; used on both examples and queries.
EMBED_PREFIX = "task: classification | query: "

# How long Ollama keeps a model loaded after its last use. Not forever (-1):
# a pinned 12B would hold ~10 GB after the router exits.
KEEP_ALIVE = "30m"

# Model for the tiebreak classifier when embeddings are unsure.
CLASSIFIER_MODEL = {"ollama": "gemma4:e2b", "litert": "gemma-4-E2B-it.litertlm"}

# Approximate resident RAM per model, measured on this Pi. Ollama under-reports
# its models' size here (it counts only part of the mmapped weights), so its own
# scheduler loads more than fits and the machine runs out of memory; make_room()
# unloads models instead to stay within RAM_BUDGET_GB.
MODEL_RAM_GB = {
        "embeddinggemma:300m": 0.7,
        "gemma4:e2b": 5.8,
        "gemma4:12b": 9.6,
        "embeddinggemma-2-text-270m.litertlm": 0.4,
        "gemma-4-E2B-it.litertlm": 3.0,
        "gemma-4-12B-it.litertlm": 7.5,
        }
RAM_BUDGET_GB = 12.0
# Models not listed above are assumed this size.
DEFAULT_RAM_GB = 6.0

# An embedding route is taken only if it scores at least MIN_SCORE and beats
# the runner-up by MIN_MARGIN; otherwise the LLM tiebreak decides.
MIN_SCORE = 0.45
MIN_MARGIN = 0.05

# Each domain: a description for the tiebreak prompt, the model to answer with,
# a profile file whose contents become the system prompt, and example prompts
# whose embeddings form the domain's centroid.
ROUTES = {
        "medical": {
            "description": "the user's health, symptoms, medications, doctors, test results",
            # "remote" runs on --remote-ollama-url; the local models answer when
            # no remote is set or it's down.
            "model": {"remote": "medgemma-1.5:4b", "ollama": "medgemma:4b", "litert": "gemma-4-12B-it.litertlm"},
            "profile": "profiles/medical.md",
            "examples": [
                "my knee hurts after running",
                "what was my last cholesterol reading?",
                "can I take ibuprofen with my blood pressure pills?",
                "I've had a headache for three days",
                "when is my next dentist appointment?",
                "is this rash something to worry about?",
                "how much vitamin D should I take?",
                "my blood sugar was 140 this morning, is that bad?",
                "I keep waking up at night, what could cause it?",
                "should I get the flu shot this year?",
                "what dose of metformin am I on?",
                "I twisted my ankle, ice or heat?",
                ],
            },
        "car": {
            "description": "the user's car: maintenance, repairs, noises, warning lights, fuel, tyres",
            "model": {"ollama": "gemma4:e2b", "litert": "gemma-4-E2B-it.litertlm"},
            "profile": "profiles/car.md",
            "examples": [
                "when is the next oil change due?",
                "the tyres are making a humming noise",
                "check engine light came on",
                "what tyre pressure should I use?",
                "how many miles since the last brake service?",
                "the car won't start in the cold",
                "is it time to replace the battery?",
                "what kind of oil does my car take?",
                "there's a squeal when I brake",
                "my fuel economy dropped recently",
                "when does the registration expire?",
                "the AC is blowing warm air",
                ],
            },
        "general": {
            "description": "anything else",
            "model": {"ollama": "gemma4:e2b", "litert": "gemma-4-E2B-it.litertlm"},
            "profile": None,
            "examples": [
                "write a haiku about autumn",
                "what's the capital of Australia?",
                "explain how a hash table works",
                "give me a recipe for banana bread",
                "translate 'good morning' into Spanish",
                "what's a good name for a cat?",
                "summarise the plot of Hamlet",
                "how do I reverse a list in Python?",
                "tell me a joke",
                "what's the difference between weather and climate?",
                ],
            },
        }
FALLBACK_ROUTE = "general"


# --- Ollama ---------------------------------------------------------------

class OllamaError(Exception):
    pass


def ollama_request(path, payload, url=None, timeout=600):
    """POST to Ollama (the local one unless url is given) and return the open response.

    Raises OllamaError with Ollama's reason on errors.
    """
    url = url or OLLAMA_URL
    # A payload of None makes a GET.
    req = urllib.request.Request(
            f"{url}{path}",
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        # Ollama puts the reason, such as an unknown model, in the response body.
        try:
            reason = json.load(e)["error"]
        except (ValueError, KeyError):
            reason = e.reason
        raise OllamaError(f"Ollama at {url} returned {e.code}: {reason}")
    except urllib.error.URLError as e:
        raise OllamaError(f"Could not reach Ollama at {url}: {e.reason}")
    except OSError as e:
        raise OllamaError(f"Could not reach Ollama at {url}: {e}")


def ollama_loaded():
    with ollama_request("/api/ps", None) as resp:
        return [m["name"] for m in json.load(resp)["models"]]


def ollama_unload(model):
    with ollama_request("/api/generate", {"model": model, "keep_alive": 0}):
        pass


def ollama_embed(texts):
    make_room(EMBED_MODEL["ollama"])
    with ollama_request("/api/embed", {"model": EMBED_MODEL["ollama"], "input": texts, "keep_alive": KEEP_ALIVE}) as resp:
        return json.load(resp)["embeddings"]


def ollama_generate(model, prompt, max_tokens, stop, temperature, on_text=None):
    """Run a raw prompt; stream chunks to on_text if given. Return the full text."""
    make_room(model)
    payload = {
            "model": model,
            "raw": True,
            "prompt": prompt,
            "stream": True,
            "keep_alive": KEEP_ALIVE,
            "options": {
                "num_predict": max_tokens,
                "stop": stop,
                "temperature": temperature,
                "num_ctx": 4096,
                },
            }
    text = ""
    with ollama_request("/api/generate", payload) as resp:
        # The streamed reply is one JSON object per line.
        for line in resp:
            chunk = json.loads(line).get("response", "")
            text += chunk
            if on_text:
                on_text(chunk)
    return text


def ollama_chat(url, model, system, prompt, on_text):
    """Answer through /api/chat, so Ollama applies the model's own chat template.

    Used for remote models, which needn't be Gemma 4 (MedGemma is Gemma 3 based).
    They don't count against this machine's RAM, so make_room() isn't called.
    """
    payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "stream": True,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_predict": 1024, "temperature": 0.7, "num_ctx": 4096},
            }
    try:
        with ollama_request("/api/chat", payload, url=url) as resp:
            for line in resp:
                on_text(json.loads(line).get("message", {}).get("content", ""))
    except OSError as e:
        # The connection can also drop mid-stream.
        raise OllamaError(f"Lost connection to Ollama at {url}: {e}")


def remote_up():
    try:
        with ollama_request("/api/version", None, url=REMOTE_OLLAMA_URL, timeout=3):
            return True
    except OllamaError:
        return False


def check_remote():
    """Warn at startup if the remote is down or lacks a route's remote model."""
    try:
        with ollama_request("/api/tags", None, url=REMOTE_OLLAMA_URL, timeout=5) as resp:
            available = {m["name"] for m in json.load(resp)["models"]}
    except OllamaError as e:
        print(f"[warning] {e}; remote routes will be {'refused' if REMOTE_ONLY else 'answered locally'} until it's back")
        return
    for name, route in ROUTES.items():
        model = route["model"].get("remote")
        if model and model not in available and f"{model}:latest" not in available:
            print(f"[warning] {model} is not on {REMOTE_OLLAMA_URL} (ollama pull {model} there); {name} will be {'refused' if REMOTE_ONLY else 'answered locally'}")


# --- LiteRT-LM ------------------------------------------------------------

_litert = None
_litert_engines = {}


def litert_module():
    global _litert
    if _litert is None:
        try:
            import litert_lm
        except ImportError:
            sys.exit("The litert backend needs the LiteRT-LM API: pip install litert-lm-api")
        # Hide the C library's INFO/WARNING startup logs.
        litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
        _litert = litert_lm
    return _litert


def litert_engine(name, embedding=False):
    # Loading a model is slow, so each file is loaded once and kept; the routes
    # that share a model file share its engine.
    if name not in _litert_engines:
        litert_lm = litert_module()
        path = os.path.join(MODELS_DIR, name)
        if not os.path.exists(path):
            sys.exit(f"LiteRT model not found: {path}")
        make_room(name)
        print(f"Loading {path}...")
        if embedding:
            _litert_engines[name] = litert_lm.EmbeddingEngine(path, backend=litert_lm.Backend.CPU())
        else:
            # The model files ship a drafter; speculative decoding roughly doubles
            # decode speed on the Pi.
            _litert_engines[name] = litert_lm.Engine(
                    path,
                    backend=litert_lm.Backend.CPU(),
                    max_num_tokens=4096,
                    enable_speculative_decoding=True,
                    )
    return _litert_engines[name]


def litert_unload(name):
    _litert_engines.pop(name).close()


def litert_embed(texts):
    litert_lm = litert_module()
    engine = litert_engine(EMBED_MODEL["litert"], embedding=True)
    responses = engine.compute_embedding_batch(texts, litert_lm.EmbeddingOptions(normalize=True))
    return [r.embedding for r in responses]


def litert_generate(model, prompt, max_tokens, stop, temperature, on_text=None):
    # A Session without the chat template takes the same raw prompt as Ollama;
    # decoding is cancelled at the first stop string, like Ollama's stop sequences.
    litert_lm = litert_module()
    engine = litert_engine(model)
    text = ""
    sent = 0
    with engine.create_session(
            apply_prompt_template=False,
            sampler_config=litert_lm.SamplerConfig(temperature=temperature),
            max_output_tokens=max_tokens,
            enable_speculative_decoding=True,
            ) as session:
        session.run_prefill([prompt])
        stopped = False
        for response in session.run_decode_async():
            if stopped:
                # Keep draining the stream until the cancel lands.
                continue
            text += response.texts[0] if response.texts else ""
            cut = min((text.find(s) for s in stop if s in text), default=-1)
            if cut >= 0:
                text = text[:cut]
                session.cancel_process()
                stopped = True
            if on_text and len(text) > sent:
                on_text(text[sent:])
                sent = len(text)
    return text


def make_room(model):
    """Unload other models, biggest first, until model fits in RAM_BUDGET_GB."""
    loaded, unload = (_litert_engines.keys(), litert_unload) if BACKEND == "litert" else (ollama_loaded(), ollama_unload)
    if model in loaded:
        return
    others = sorted(loaded, key=ram_gb, reverse=True)
    used = sum(ram_gb(m) for m in others)
    for other in others:
        if used + ram_gb(model) <= RAM_BUDGET_GB:
            break
        print(f"[memory] unloading {other} to fit {model}")
        unload(other)
        used -= ram_gb(other)


def ram_gb(model):
    # Ollama's /api/ps adds ":latest" to untagged names.
    return MODEL_RAM_GB.get(model, MODEL_RAM_GB.get(model.removesuffix(":latest"), DEFAULT_RAM_GB))


def embed(texts):
    vectors = litert_embed(texts) if BACKEND == "litert" else ollama_embed(texts)
    return [normalize(v) for v in vectors]


def generate(model, prompt, max_tokens, stop, temperature, on_text=None):
    gen = litert_generate if BACKEND == "litert" else ollama_generate
    return gen(model, prompt, max_tokens, stop, temperature, on_text)


# --- Routing --------------------------------------------------------------

def normalize(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def build_centroids():
    """Return {domain: unit centroid of its example embeddings}, cached on disk."""
    # The cache is keyed on the examples and the embedding model, so editing
    # ROUTES or switching backend recomputes it.
    source = {name: route["examples"] for name, route in ROUTES.items()}
    key = hashlib.sha256(json.dumps([EMBED_MODEL[BACKEND], EMBED_PREFIX, source], sort_keys=True).encode()).hexdigest()
    try:
        with open(CENTROIDS_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    if key in cache:
        return cache[key]

    print(f"Embedding route examples with {EMBED_MODEL[BACKEND]}...")
    centroids = {}
    for name, examples in source.items():
        vectors = embed([EMBED_PREFIX + e for e in examples])
        centroids[name] = normalize([sum(col) / len(vectors) for col in zip(*vectors)])
    cache[key] = centroids
    with open(CENTROIDS_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    return centroids


def classify_message(prompt):
    choices = "\n".join(f"- {name}: {route['description']}" for name, route in ROUTES.items())
    return (
            "Classify the user's message into exactly one category.\n"
            f"Categories:\n{choices}\n\n"
            f"Message: {prompt}\n\n"
            "Reply with the category name only."
            )


def llm_classify(prompt):
    # Raw Gemma 4 turn format with the reply prefilled, so the model only has to
    # emit the label; a handful of tokens and a newline stop keep it short.
    raw = (
            "<|turn>user\n"
            f"{classify_message(prompt)}<turn|>\n"
            "<|turn>model\n"
            "Category:"
            )
    reply = generate(CLASSIFIER_MODEL[BACKEND], raw, max_tokens=6, stop=["\n", "<turn|>"], temperature=0.0)
    label = reply.strip().strip(".*`'\"").lower()
    return label if label in ROUTES else FALLBACK_ROUTE


def classify(prompt, centroids, show_scores):
    """Return the domain for prompt, printing how it was decided."""
    start = time.perf_counter()
    query = embed([EMBED_PREFIX + prompt])[0]
    scores = sorted(((dot(query, c), name) for name, c in centroids.items()), reverse=True)
    (top, name), (second, _) = scores[0], scores[1]
    ms = (time.perf_counter() - start) * 1000
    if show_scores:
        print("[scores] " + "  ".join(f"{n} {s:.3f}" for s, n in scores))

    if top >= MIN_SCORE and top - second >= MIN_MARGIN:
        print(f"[route] {name} {top:.2f} (margin {top - second:.2f}) in {ms:.0f} ms")
        return name

    start = time.perf_counter()
    name = llm_classify(prompt)
    tiebreak_ms = (time.perf_counter() - start) * 1000
    print(f"[route] {name} by tiebreak in {tiebreak_ms:.0f} ms (embeddings unsure: {top:.2f}, margin {top - second:.2f}, {ms:.0f} ms)")
    return name


# --- Answering ------------------------------------------------------------

def system_prompt(route):
    # The domain's profile goes in the system turn, so the model answers with that history.
    # Today's date is included so the model can work out what's due.
    system = f"Today is {time.strftime('%Y-%m-%d')}."
    if route["profile"]:
        try:
            with open(os.path.join(HERE, route["profile"]), encoding="utf-8") as f:
                system += "\n\n" + f.read().strip()
        except OSError:
            pass
    return system


def answer_prompt(route, prompt):
    return (
            f"<|turn>system\n{system_prompt(route)}<turn|>\n"
            "<|turn>user\n"
            f"{prompt}<turn|>\n"
            "<|turn>model\n"
            )


THOUGHT_START = "<|channel>"
THOUGHT_END = "<channel|>"


def thought_filter(on_text):
    """Wrap on_text to drop a leading <|channel>...<channel|> thought block.

    The 12B opens its reply with an empty one even with thinking off; prefilling
    it instead would make the E2B actually think, so it's stripped from the output.
    """
    pending = ""
    done = False

    def feed(chunk):
        nonlocal pending, done
        if done:
            on_text(chunk)
            return
        pending += chunk
        if pending.startswith(THOUGHT_START) or THOUGHT_START.startswith(pending):
            # Hold the text back until the block closes.
            if THOUGHT_END not in pending:
                return
            pending = pending.split(THOUGHT_END, 1)[1].lstrip()
        done = True
        on_text(pending)

    return feed


def print_chunk(chunk):
    print(chunk, end="", flush=True)


def answer(name, prompt):
    route = ROUTES[name]
    # A route with a remote model uses it when --remote-ollama-url is set and
    # reachable, and falls back to its local model otherwise.
    # With --remote-only it fails instead of falling back.
    remote = route["model"].get("remote")
    fallback_note = "not answered (--remote-only)" if REMOTE_ONLY else "answering locally"
    if remote and not REMOTE_OLLAMA_URL and REMOTE_ONLY:
        print(f"[no --remote-ollama-url set; {fallback_note}]")
        return
    if remote and REMOTE_OLLAMA_URL:
        if remote_up():
            print(f"[{remote} on {REMOTE_OLLAMA_URL}]")
            try:
                ollama_chat(REMOTE_OLLAMA_URL, remote, system_prompt(route), prompt, thought_filter(print_chunk))
                print()
                return
            except OllamaError as e:
                print(f"\n[{e}; {fallback_note}]")
        else:
            print(f"[{REMOTE_OLLAMA_URL} is unreachable; {fallback_note}]")
        if REMOTE_ONLY:
            return

    model = route["model"][BACKEND]
    # A route whose LiteRT file hasn't been downloaded answers with the general
    # route's model instead of exiting; the profile still applies.
    if BACKEND == "litert" and not os.path.exists(os.path.join(MODELS_DIR, model)):
        fallback = ROUTES[FALLBACK_ROUTE]["model"]["litert"]
        print(f"[{model} not found in {MODELS_DIR}; using {fallback}]")
        model = fallback
    print(f"[{model}]")
    generate(model, answer_prompt(route, prompt), max_tokens=1024, stop=["<turn|>"], temperature=0.7,
             on_text=thought_filter(print_chunk))
    print()


parser = argparse.ArgumentParser(description="Route each prompt to a domain-specific local Gemma model and profile.")
parser.add_argument("--backend", choices=["ollama", "litert"], default=BACKEND)
parser.add_argument("--ollama-url", default=OLLAMA_URL, help="Ollama server URL, e.g. http://192.168.1.50:11434")
parser.add_argument("--remote-ollama-url", default=REMOTE_OLLAMA_URL, help="Ollama server for routes with a remote model (medical), e.g. http://192.168.1.50:11434")
parser.add_argument("--remote-only", action="store_true", default=REMOTE_ONLY, help="never answer remote routes locally; fail if the remote is unset or down")
parser.add_argument("--models-dir", default=MODELS_DIR, help="directory holding the .litertlm model files")
parser.add_argument("--show-scores", action="store_true", help="print every domain's similarity score")
args = parser.parse_args()
BACKEND = args.backend
OLLAMA_URL = args.ollama_url.rstrip("/")
MODELS_DIR = os.path.expanduser(args.models_dir)
REMOTE_OLLAMA_URL = args.remote_ollama_url and args.remote_ollama_url.rstrip("/")
REMOTE_ONLY = args.remote_only
print(f"Using {BACKEND} ({MODELS_DIR if BACKEND == 'litert' else OLLAMA_URL})")
if REMOTE_OLLAMA_URL:
    print(f"Remote routes use {REMOTE_OLLAMA_URL}")
    check_remote()

try:
    centroids = build_centroids()
    while prompt := input("\nAsk (empty line to quit): ").strip():
        answer(classify(prompt, centroids, args.show_scores), prompt)
except OllamaError as e:
    # A local Ollama failure ends the session, as before.
    sys.exit(str(e))
