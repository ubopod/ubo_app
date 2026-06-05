"""Regression tests for the local-Ollama readiness refresh.

When an Ollama model finishes downloading, the core dispatches
``AssistantSetSelectedModelAction`` with the *already-selected* model, which
the reducer turns into an ``AssistantModelChangedEvent`` carrying the same
model name. The subprocess must rebuild the active Ollama service on that
event — the ``OLLamaLLMService`` created when Ollama was first selected may
have started against a not-yet-running daemon (the model wasn't downloaded
yet), so without a rebuild the assistant stays silent until a full restart.

The same-name dedup must still hold for API-key providers (no readiness
handshake) and for inactive providers.
"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar, cast

from ubo_bindings.ubo.v1 import (
    AssistantLlmName,
    AssistantModelChangedEvent,
    Event,
)

from ubo_assistant.ubo_llm import LLMServiceConfig, UboLLMService

if TYPE_CHECKING:
    from ubo_bindings.client import UboRPCClient

F = TypeVar('F', bound=Callable[..., object])


class FakeClient:
    """Minimal client surface used by UboLLMService construction."""

    def dispatch(self, *, action: object) -> None:
        """Ignore dispatched assistance reports."""
        _ = action

    def autorun(self, selectors: list[str]) -> Callable[[F], F]:
        """Return a decorator without invoking it."""
        _ = selectors

        def decorator(function: F) -> F:
            return function

        return decorator


class OllamaReadinessRefreshTests(unittest.IsolatedAsyncioTestCase):
    """``_handle_model_changed_event`` refresh behavior."""

    def _make_service(self) -> UboLLMService:
        service = UboLLMService(
            client=cast('UboRPCClient', FakeClient()),
            config=LLMServiceConfig(),
            selector='state.assistant.selected_llm',
        )
        # Record refreshes instead of building real Pipecat services.
        self._ollama_refreshes = 0
        self._api_key_refreshes: list[str] = []
        self._scheduled: list[object] = []

        async def fake_refresh_ollama() -> None:
            self._ollama_refreshes += 1

        async def fake_refresh_api_key(service_id: str) -> None:
            self._api_key_refreshes.append(service_id)

        def fake_create_task(coro: object) -> object:
            self._scheduled.append(coro)
            return asyncio.ensure_future(cast('asyncio.Future', coro))

        service._refresh_ollama_service = fake_refresh_ollama  # type: ignore[method-assign]  # noqa: SLF001
        service._refresh_api_key_service = fake_refresh_api_key  # type: ignore[method-assign]  # noqa: SLF001
        service.create_task = fake_create_task  # type: ignore[method-assign]
        return service

    @staticmethod
    def _model_changed(llm_name: AssistantLlmName, model: str) -> Event:
        return Event(
            assistant_model_changed_event=AssistantModelChangedEvent(
                llm_name=llm_name,
                model=model,
            ),
        )

    async def test_same_model_refreshes_active_ollama(self) -> None:
        """A same-name model change rebuilds the active Ollama service."""
        service = self._make_service()
        service._current_service_id = 'ollama'  # noqa: SLF001
        service._config.selected_models['ollama'] = 'gemma3:1b'  # noqa: SLF001

        service._handle_model_changed_event(  # noqa: SLF001
            self._model_changed(AssistantLlmName.OLLAMA, 'gemma3:1b'),
        )
        await asyncio.sleep(0)

        self.assertEqual(self._ollama_refreshes, 1)  # noqa: PT009
        self.assertEqual(self._api_key_refreshes, [])  # noqa: PT009

    async def test_same_model_does_not_refresh_inactive_ollama(self) -> None:
        """When Ollama isn't the active provider, nothing is rebuilt."""
        service = self._make_service()
        service._current_service_id = 'openai'  # noqa: SLF001
        service._config.selected_models['ollama'] = 'gemma3:1b'  # noqa: SLF001

        service._handle_model_changed_event(  # noqa: SLF001
            self._model_changed(AssistantLlmName.OLLAMA, 'gemma3:1b'),
        )
        await asyncio.sleep(0)

        self.assertEqual(self._ollama_refreshes, 0)  # noqa: PT009

    async def test_same_model_does_not_refresh_active_api_key(self) -> None:
        """API-key providers keep the dedup on redundant re-selection."""
        service = self._make_service()
        service._current_service_id = 'openai'  # noqa: SLF001
        service._config.selected_models['openai'] = 'gpt-4o-mini'  # noqa: SLF001

        service._handle_model_changed_event(  # noqa: SLF001
            self._model_changed(AssistantLlmName.OPENAI, 'gpt-4o-mini'),
        )
        await asyncio.sleep(0)

        self.assertEqual(self._api_key_refreshes, [])  # noqa: PT009

    async def test_changed_model_refreshes_active_api_key(self) -> None:
        """A genuine model change still refreshes the active API-key provider."""
        service = self._make_service()
        service._current_service_id = 'openai'  # noqa: SLF001
        service._config.selected_models['openai'] = 'gpt-4o-mini'  # noqa: SLF001

        service._handle_model_changed_event(  # noqa: SLF001
            self._model_changed(AssistantLlmName.OPENAI, 'gpt-4.1'),
        )
        await asyncio.sleep(0)

        self.assertEqual(self._api_key_refreshes, ['openai'])  # noqa: PT009


if __name__ == '__main__':
    unittest.main()
