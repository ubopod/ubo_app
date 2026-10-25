"""Tests for ``DomainClassifier`` against a fake Ollama HTTP server."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer
from pipecat.processors.aggregators.llm_context import LLMContext

from ubo_assistant.domain_classifier import (
    DOMAIN_ROUTES,
    EMBED_PREFIX,
    DomainClassifier,
    OllamaClient,
    _centroids_key,
)
from ubo_assistant.prompt_router import RoutingDecision, RoutingRequest

_AXIS = {'medical': [1.0, 0.0, 0.0], 'car': [0.0, 1.0, 0.0], 'general': [0.0, 0.0, 1.0]}
_EXAMPLE_DOMAIN = {
    example: route.name for route in DOMAIN_ROUTES for example in route.examples
}
# Halfway between medical and car: the embeddings can't tell them apart.
_AMBIGUOUS = [1.0, 1.0, 0.0]
ALL_CANDIDATES = ('ollama', 'ollama_onprem')


class FakeOllama:
    """Ollama's /api/embed, /api/generate and /api/version, recording calls."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.queries: dict[str, list[float]] = {}
        self.tiebreak_reply = ' car'
        self.embed_status = 200
        self.embedded: list[str] = []
        self.generated: list[str] = []

    def app(self) -> web.Application:
        """Build the aiohttp app."""
        app = web.Application()
        app.router.add_post('/api/embed', self._embed)
        app.router.add_post('/api/generate', self._generate)
        app.router.add_get('/api/version', self._version)
        return app

    async def _embed(self, request: web.Request) -> web.Response:
        if self.embed_status != 200:  # noqa: PLR2004
            return web.json_response(
                {'error': 'model "embeddinggemma:300m" not found'},
                status=self.embed_status,
            )
        body = await request.json()
        texts = [text.removeprefix(EMBED_PREFIX) for text in body['input']]
        self.embedded.extend(texts)
        return web.json_response(
            {
                'embeddings': [
                    self.queries.get(text)
                    or _AXIS[_EXAMPLE_DOMAIN.get(text, 'general')]
                    for text in texts
                ],
            },
        )

    async def _generate(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.generated.append(body['prompt'])
        return web.json_response({'response': self.tiebreak_reply})

    async def _version(self, _request: web.Request) -> web.Response:
        return web.json_response({'version': '0.0.0'})


def _decided(decision: RoutingDecision | None) -> RoutingDecision:
    """Narrow to a decision, failing the test on ``None``."""
    if decision is None:
        msg = 'expected a routing decision'
        raise AssertionError(msg)
    return decision


def _request(text: str, candidates: tuple[str, ...] = ALL_CANDIDATES) -> RoutingRequest:
    return RoutingRequest(
        text=text,
        context=LLMContext([{'role': 'user', 'content': text}]),
        candidates=candidates,
    )


class DomainClassifierTests(unittest.IsolatedAsyncioTestCase):
    """Classification, target choice and the system addendum."""

    async def asyncSetUp(self) -> None:
        """Serve a fake Ollama and point a classifier at it."""
        self.ollama = FakeOllama()
        self.server = TestServer(self.ollama.app())
        await self.server.start_server()
        self.url = str(self.server.make_url('')).rstrip('/')
        self.tmp = Path(tempfile.mkdtemp())
        self.centroids_path = self.tmp / 'routing' / 'centroids.json'
        self.profiles_path = self.tmp / 'routing' / 'profiles'
        self.profiles_path.mkdir(parents=True)
        (self.profiles_path / 'car.md').write_text('Car: 2019 Civic, oil due May.\n')

    async def asyncTearDown(self) -> None:
        """Stop the fake Ollama."""
        await self.server.close()

    def _classifier(self, *, remote: OllamaClient | None = None) -> DomainClassifier:
        return DomainClassifier(
            local=OllamaClient(self.url),
            remote=remote,
            centroids_path=self.centroids_path,
            profiles_path=self.profiles_path,
        )

    async def test_clear_prompt_is_decided_by_embeddings(self) -> None:
        """A confident embedding match skips the LLM tiebreak."""
        self.ollama.queries['oil change?'] = _AXIS['car']

        decision = _decided(
            await self._classifier().classify(_request('oil change?')),
        )

        self.assertEqual(  # noqa: PT009
            (decision.provider_id, decision.model),
            ('ollama', 'gemma4:e2b'),
        )
        self.assertEqual(self.ollama.generated, [])  # noqa: PT009

    async def test_addendum_has_the_date_and_the_domain_profile(self) -> None:
        """The car profile is appended; general (no profile) gets only the date."""
        self.ollama.queries['oil change?'] = _AXIS['car']
        self.ollama.queries['tell me a joke'] = _AXIS['general']
        classifier = self._classifier()

        car = _decided(await classifier.classify(_request('oil change?')))
        general = _decided(await classifier.classify(_request('tell me a joke')))

        self.assertRegex(  # noqa: PT009
            car.system_addendum,
            r'^Today is \d{4}-\d{2}-\d{2}\.\n\nCar: 2019 Civic, oil due May\.$',
        )
        self.assertRegex(general.system_addendum, r'^Today is \d{4}-\d{2}-\d{2}\.$')  # noqa: PT009

    async def test_unsure_embeddings_use_the_tiebreak(self) -> None:
        """A low margin asks the LLM, whose label decides."""
        self.ollama.queries['my back hurts when I drive'] = _AMBIGUOUS
        self.ollama.tiebreak_reply = ' Car.'

        decision = _decided(
            await self._classifier().classify(_request('my back hurts when I drive')),
        )

        self.assertIn('Civic', decision.system_addendum)  # noqa: PT009
        self.assertEqual(len(self.ollama.generated), 1)  # noqa: PT009
        self.assertTrue(self.ollama.generated[0].endswith('Category:'))  # noqa: PT009

    async def test_unknown_tiebreak_label_means_general(self) -> None:
        """A label outside the domains falls back to general."""
        self.ollama.queries['hmm'] = _AMBIGUOUS
        self.ollama.tiebreak_reply = ' sports'

        decision = _decided(await self._classifier().classify(_request('hmm')))

        self.assertNotIn('Civic', decision.system_addendum)  # noqa: PT009
        self.assertEqual(decision.model, 'gemma4:e2b')  # noqa: PT009

    async def test_missing_model_abstains(self) -> None:
        """An Ollama error (e.g. model not pulled) returns None, so AUTO falls back."""
        self.ollama.embed_status = 404

        self.assertIsNone(await self._classifier().classify(_request('hi')))  # noqa: PT009

    async def test_ollama_down_abstains(self) -> None:
        """No Ollama at all also returns None."""
        classifier = DomainClassifier(
            local=OllamaClient('http://127.0.0.1:1'),
            centroids_path=self.centroids_path,
            profiles_path=self.profiles_path,
        )

        self.assertIsNone(await classifier.classify(_request('hi')))  # noqa: PT009

    async def test_empty_text_abstains_without_calling_ollama(self) -> None:
        """An image-only turn isn't classified."""
        self.assertIsNone(await self._classifier().classify(_request('  ')))  # noqa: PT009
        self.assertEqual(self.ollama.embedded, [])  # noqa: PT009

    async def test_medical_prefers_the_reachable_remote(self) -> None:
        """The remote target answers when it's configured and up."""
        self.ollama.queries['knee pain'] = _AXIS['medical']
        classifier = self._classifier(remote=OllamaClient(self.url))

        decision = _decided(await classifier.classify(_request('knee pain')))

        self.assertEqual(  # noqa: PT009
            (decision.provider_id, decision.model),
            ('ollama_onprem', 'medgemma-1.5:4b'),
        )

    async def test_medical_answers_locally_when_the_remote_is_down(self) -> None:
        """An unreachable remote is skipped for the local medical model."""
        self.ollama.queries['knee pain'] = _AXIS['medical']
        classifier = self._classifier(remote=OllamaClient('http://127.0.0.1:1'))

        decision = _decided(await classifier.classify(_request('knee pain')))

        self.assertEqual(  # noqa: PT009
            (decision.provider_id, decision.model),
            ('ollama', 'medgemma:4b'),
        )

    async def test_medical_answers_locally_without_the_remote_provider(self) -> None:
        """A remote that isn't a candidate (no URL configured) is skipped."""
        self.ollama.queries['knee pain'] = _AXIS['medical']

        decision = _decided(
            await self._classifier().classify(
                _request('knee pain', candidates=('ollama',)),
            ),
        )

        self.assertEqual(decision.provider_id, 'ollama')  # noqa: PT009

    async def test_no_available_target_abstains(self) -> None:
        """Without any target's provider, the fallback answers."""
        self.ollama.queries['oil change?'] = _AXIS['car']

        decision = await self._classifier().classify(
            _request('oil change?', candidates=('anthropic',)),
        )

        self.assertIsNone(decision)  # noqa: PT009

    async def test_centroids_are_cached_on_disk(self) -> None:
        """A second classifier reuses the cache instead of re-embedding examples."""
        self.ollama.queries['oil change?'] = _AXIS['car']
        await self._classifier().classify(_request('oil change?'))
        self.ollama.embedded.clear()

        await self._classifier().classify(_request('oil change?'))

        self.assertEqual(self.ollama.embedded, ['oil change?'])  # noqa: PT009
        cache = json.loads(self.centroids_path.read_text())
        self.assertIn(_centroids_key(), cache)  # noqa: PT009

    async def test_stale_cache_is_rebuilt(self) -> None:
        """Centroids cached for other examples or another model are ignored."""
        self.centroids_path.parent.mkdir(parents=True, exist_ok=True)
        self.centroids_path.write_text(json.dumps({'stale': {'car': [1.0]}}))

        await self._classifier().warm_up()

        example_count = sum(len(route.examples) for route in DOMAIN_ROUTES)
        self.assertEqual(len(self.ollama.embedded), example_count)  # noqa: PT009

    async def test_warm_up_never_raises(self) -> None:
        """Warm-up with Ollama down only logs."""
        self.ollama.embed_status = 500

        await self._classifier().warm_up()


if __name__ == '__main__':
    unittest.main()
