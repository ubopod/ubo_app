"""Domain classifier for per-prompt routing, ported from the ``routing/`` prototype.

Each prompt is put in one domain (``medical``, ``car`` or ``general``):

1. Embedding nearest-centroid (~0.35 s on a Pi 5). The prompt is embedded with
   EmbeddingGemma and compared with one centroid per domain, the mean of that
   domain's example embeddings. The top domain wins if it scores at least
   ``MIN_SCORE`` and beats the runner-up by ``MIN_MARGIN``.
2. LLM tiebreak (~2.7 s), only when the embeddings are unsure: a raw Gemma 4
   prompt with the reply prefilled, asking for the label alone.

The domain picks the provider/model (the first of its targets that is available)
and a system-message addendum: today's date plus the domain's profile, a
plain-text file under ``DATA_PATH/routing/profiles/<domain>.md``. Profiles hold
personal history, so they stay on disk in this subprocess and never enter the
store. Everything talks to Ollama's HTTP API; the models must already be pulled.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp
from loguru import logger

from ubo_assistant.constants import DATA_PATH
from ubo_assistant.prompt_router import RoutingDecision

if TYPE_CHECKING:
    from pathlib import Path

    from ubo_assistant.prompt_router import RoutingRequest

LOCAL_OLLAMA_URL = 'http://localhost:11434'
# Ubo service id of the remote Ollama; its targets are skipped while it's down.
REMOTE_PROVIDER_ID = 'ollama_onprem'
REMOTE_CHECK_TIMEOUT_SECS = 1.5

EMBED_MODEL = 'embeddinggemma:300m'
# EmbeddingGemma's classification prompt, used on both examples and queries.
EMBED_PREFIX = 'task: classification | query: '
TIEBREAK_MODEL = 'gemma4:e2b'
# Not forever: a pinned model would hold its RAM after the assistant stops.
KEEP_ALIVE = '30m'

MIN_SCORE = 0.45
MIN_MARGIN = 0.05
FALLBACK_DOMAIN = 'general'

ROUTING_PATH = DATA_PATH / 'routing'
PROFILES_PATH = ROUTING_PATH / 'profiles'
CENTROIDS_PATH = ROUTING_PATH / 'centroids.json'


@dataclass(frozen=True)
class RouteTarget:
    """A provider/model a domain can be answered with."""

    provider_id: str
    model: str


@dataclass(frozen=True)
class DomainRoute:
    """One domain: tiebreak description, answer targets and centroid examples."""

    name: str
    description: str
    # In preference order; the first available one answers.
    targets: tuple[RouteTarget, ...]
    examples: tuple[str, ...]


DOMAIN_ROUTES: tuple[DomainRoute, ...] = (
    DomainRoute(
        name='medical',
        description="the user's health, symptoms, medications, doctors, test results",
        targets=(
            RouteTarget(REMOTE_PROVIDER_ID, 'medgemma-1.5:4b'),
            RouteTarget('ollama', 'medgemma:4b'),
        ),
        examples=(
            'my knee hurts after running',
            'what was my last cholesterol reading?',
            'can I take ibuprofen with my blood pressure pills?',
            "I've had a headache for three days",
            'when is my next dentist appointment?',
            'is this rash something to worry about?',
            'how much vitamin D should I take?',
            'my blood sugar was 140 this morning, is that bad?',
            'I keep waking up at night, what could cause it?',
            'should I get the flu shot this year?',
            'what dose of metformin am I on?',
            'I twisted my ankle, ice or heat?',
        ),
    ),
    DomainRoute(
        name='car',
        description=(
            "the user's car: maintenance, repairs, noises, warning lights, fuel, tyres"
        ),
        targets=(RouteTarget('ollama', 'gemma4:e2b'),),
        examples=(
            'when is the next oil change due?',
            'the tyres are making a humming noise',
            'check engine light came on',
            'what tyre pressure should I use?',
            'how many miles since the last brake service?',
            "the car won't start in the cold",
            'is it time to replace the battery?',
            'what kind of oil does my car take?',
            "there's a squeal when I brake",
            'my fuel economy dropped recently',
            'when does the registration expire?',
            'the AC is blowing warm air',
        ),
    ),
    DomainRoute(
        name='general',
        description='anything else',
        targets=(RouteTarget('ollama', 'gemma4:e2b'),),
        examples=(
            'write a haiku about autumn',
            "what's the capital of Australia?",
            'explain how a hash table works',
            'give me a recipe for banana bread',
            "translate 'good morning' into Spanish",
            "what's a good name for a cat?",
            'summarise the plot of Hamlet',
            'how do I reverse a list in Python?',
            'tell me a joke',
            "what's the difference between weather and climate?",
        ),
    ),
)
_ROUTES_BY_NAME = {route.name: route for route in DOMAIN_ROUTES}

Vector = list[float]


def _normalize(vector: Vector) -> Vector:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _dot(a: Vector, b: Vector) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _centroids_key() -> str:
    """Cache key over the examples and embedding model, as the prototype computes it."""
    source = {route.name: list(route.examples) for route in DOMAIN_ROUTES}
    return hashlib.sha256(
        json.dumps([EMBED_MODEL, EMBED_PREFIX, source], sort_keys=True).encode(),
    ).hexdigest()


def tiebreak_prompt(text: str) -> str:
    """Raw Gemma 4 turn asking for the label, with the reply prefilled."""
    choices = '\n'.join(
        f'- {route.name}: {route.description}' for route in DOMAIN_ROUTES
    )
    return (
        '<|turn>user\n'
        "Classify the user's message into exactly one category.\n"
        f'Categories:\n{choices}\n\n'
        f'Message: {text}\n\n'
        'Reply with the category name only.<turn|>\n'
        '<|turn>model\n'
        'Category:'
    )


class OllamaClient:
    """The few Ollama HTTP calls the classifier needs."""

    def __init__(self, base_url: str) -> None:
        """Talk to the Ollama server at ``base_url``."""
        self.base_url = base_url.rstrip('/')

    async def embed(self, texts: list[str]) -> list[Vector]:
        """Return one embedding per text."""
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f'{self.base_url}/api/embed',
                json={'model': EMBED_MODEL, 'input': texts, 'keep_alive': KEEP_ALIVE},
            ) as response,
        ):
            response.raise_for_status()
            body = await response.json()
        return body['embeddings']

    async def generate(self, prompt: str, *, max_tokens: int, stop: list[str]) -> str:
        """Run a raw prompt with temperature 0 and return the whole reply."""
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                f'{self.base_url}/api/generate',
                json={
                    'model': TIEBREAK_MODEL,
                    'raw': True,
                    'prompt': prompt,
                    'stream': False,
                    'keep_alive': KEEP_ALIVE,
                    'options': {
                        'num_predict': max_tokens,
                        'stop': stop,
                        'temperature': 0.0,
                    },
                },
            ) as response,
        ):
            response.raise_for_status()
            body = await response.json()
        return body['response']

    async def is_up(self) -> bool:
        """Whether the server answers within ``REMOTE_CHECK_TIMEOUT_SECS``."""
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=REMOTE_CHECK_TIMEOUT_SECS),
                ) as session,
                session.get(f'{self.base_url}/api/version') as response,
            ):
                return response.ok
        except (aiohttp.ClientError, TimeoutError):
            return False


class DomainClassifier:
    """``PromptClassifier`` that routes by domain."""

    def __init__(
        self,
        *,
        local: OllamaClient | None = None,
        remote: OllamaClient | None = None,
        centroids_path: Path = CENTROIDS_PATH,
        profiles_path: Path = PROFILES_PATH,
    ) -> None:
        """Classify with the local Ollama; ``remote`` is the on-prem Ollama, if any."""
        self._local = local or OllamaClient(LOCAL_OLLAMA_URL)
        self._remote = remote
        self._centroids_path = centroids_path
        self._profiles_path = profiles_path
        self._centroids: dict[str, Vector] | None = None
        self._centroids_lock = asyncio.Lock()

    async def warm_up(self) -> None:
        """Load the embedding model and centroids before the first prompt."""
        start = time.perf_counter()
        logger.info(
            '[routing] classifier warm-up started {extra}',
            extra={'model': EMBED_MODEL},
        )
        try:
            await self._get_centroids()
        except (aiohttp.ClientError, TimeoutError) as exception:
            logger.warning(
                '[routing] classifier warm-up failed {extra}',
                extra={'error': repr(exception), 'model': EMBED_MODEL},
            )
            return
        logger.info(
            '[routing] classifier warm-up done {extra}',
            extra={'ms': round((time.perf_counter() - start) * 1000)},
        )

    async def classify(self, request: RoutingRequest) -> RoutingDecision | None:
        """Return the domain's target, or ``None`` when Ollama can't classify."""
        if not request.text.strip():
            logger.info('[routing] classifier skipped: no text in the turn')
            return None
        try:
            domain = await self._classify_domain(request.text)
        except (aiohttp.ClientError, TimeoutError) as exception:
            # Typically a model that isn't pulled (404) or Ollama not running.
            logger.warning(
                '[routing] classifier unavailable; abstaining {extra}',
                extra={'error': repr(exception)},
            )
            return None

        route = _ROUTES_BY_NAME[domain]
        target = await self._pick_target(route, request.candidates)
        if target is None:
            logger.warning(
                '[routing] classifier: no available provider for domain; abstaining '
                '{extra}',
                extra={'domain': domain, 'candidates': request.candidates},
            )
            return None
        profile = self._read_profile(route)
        # Name and size only: profiles hold personal history.
        profile_summary = f'{route.name}.md ({len(profile)} chars)' if profile else None
        logger.info(
            '[routing] classifier decision {extra}',
            extra={
                'domain': domain,
                'provider_id': target.provider_id,
                'model': target.model,
                'profile': profile_summary,
            },
        )
        return RoutingDecision(
            provider_id=target.provider_id,
            model=target.model,
            system_addendum=self._system_addendum(profile),
        )

    async def _classify_domain(self, text: str) -> str:
        start = time.perf_counter()
        centroids = await self._get_centroids()
        query = _normalize((await self._local.embed([EMBED_PREFIX + text]))[0])
        scores = sorted(
            ((_dot(query, centroid), name) for name, centroid in centroids.items()),
            reverse=True,
        )
        (top, name), (second, _) = scores[0], scores[1]
        embed_ms = round((time.perf_counter() - start) * 1000)
        stage_1 = {
            'scores': {domain: round(score, 3) for score, domain in scores},
            'margin': round(top - second, 3),
            'embed_ms': embed_ms,
        }
        if top >= MIN_SCORE and top - second >= MIN_MARGIN:
            logger.info(
                '[routing] classifier domain {extra}',
                extra={'domain': name, 'decided_by': 'embeddings', **stage_1},
            )
            return name

        start = time.perf_counter()
        reply = await self._local.generate(
            tiebreak_prompt(text),
            max_tokens=6,
            stop=['\n', '<turn|>'],
        )
        label = reply.strip().strip('.*`\'"').lower()
        domain = label if label in _ROUTES_BY_NAME else FALLBACK_DOMAIN
        logger.info(
            '[routing] classifier domain {extra}',
            extra={
                'domain': domain,
                'decided_by': 'tiebreak',
                'tiebreak_reply': reply,
                'tiebreak_ms': round((time.perf_counter() - start) * 1000),
                **stage_1,
            },
        )
        return domain

    async def _get_centroids(self) -> dict[str, Vector]:
        async with self._centroids_lock:
            if self._centroids is None:
                self._centroids = await self._load_or_build_centroids()
            return self._centroids

    async def _load_or_build_centroids(self) -> dict[str, Vector]:
        key = _centroids_key()
        try:
            cache: dict[str, dict[str, Vector]] = json.loads(
                self._centroids_path.read_text(encoding='utf-8'),
            )
        except FileNotFoundError:
            cache = {}
        if key in cache:
            logger.info(
                '[routing] classifier centroids loaded from cache {extra}',
                extra={'path': str(self._centroids_path)},
            )
            return cache[key]

        logger.info(
            '[routing] classifier embedding routing examples {extra}',
            extra={'model': EMBED_MODEL},
        )
        centroids: dict[str, Vector] = {}
        for route in DOMAIN_ROUTES:
            vectors = [
                _normalize(vector)
                for vector in await self._local.embed(
                    [EMBED_PREFIX + example for example in route.examples],
                )
            ]
            centroids[route.name] = _normalize(
                [sum(column) / len(vectors) for column in zip(*vectors, strict=True)],
            )
        cache[key] = centroids
        self._centroids_path.parent.mkdir(parents=True, exist_ok=True)
        self._centroids_path.write_text(json.dumps(cache), encoding='utf-8')
        return centroids

    async def _pick_target(
        self,
        route: DomainRoute,
        candidates: tuple[str, ...],
    ) -> RouteTarget | None:
        for target in route.targets:
            if target.provider_id not in candidates:
                logger.info(
                    '[routing] classifier skipped target: provider not available '
                    '{extra}',
                    extra={'provider_id': target.provider_id, 'model': target.model},
                )
                continue
            if (
                target.provider_id == REMOTE_PROVIDER_ID
                and self._remote is not None
                and not await self._remote.is_up()
            ):
                logger.warning(
                    '[routing] classifier skipped target: remote Ollama unreachable '
                    '{extra}',
                    extra={
                        'url': self._remote.base_url,
                        'model': target.model,
                        'domain': route.name,
                    },
                )
                continue
            return target
        return None

    def _read_profile(self, route: DomainRoute) -> str:
        """Return the domain's profile text, or ``''`` when it has none."""
        profile_path = self._profiles_path / f'{route.name}.md'
        if not profile_path.exists():
            return ''
        return profile_path.read_text(encoding='utf-8').strip()

    @staticmethod
    def _system_addendum(profile: str) -> str:
        """Today's date, so the model can work out what's due, and the profile."""
        addendum = f'Today is {time.strftime("%Y-%m-%d")}.'
        if profile:
            addendum += '\n\n' + profile
        return addendum
