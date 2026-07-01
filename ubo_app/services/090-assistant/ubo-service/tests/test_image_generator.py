"""Construction tests for the image-generator switch service.

Pure construction — no network. Verifies the Venice branch wires an
OpenAI-compatible generator pointed at Venice's base URL, and that omitting the
key leaves the slot empty.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar, cast

from ubo_assistant.ubo_image_generator import (
    VENICE_BASE_URL,
    UboImageGeneratorService,
    UboOpenAIImageGenService,
)

if TYPE_CHECKING:
    from ubo_bindings.client import UboRPCClient

F = TypeVar('F', bound=Callable[..., object])


class FakeClient:
    """Minimal client surface used by switch-service construction."""

    def dispatch(self, *, action: object) -> None:
        """Ignore dispatched assistance reports."""
        _ = action

    def autorun(self, selectors: list[str]) -> Callable[[F], F]:
        """Return a decorator without invoking it."""
        _ = selectors

        def decorator(function: F) -> F:
            return function

        return decorator


def _build(venice_api_key: str | None) -> UboImageGeneratorService:
    return UboImageGeneratorService(
        client=cast('UboRPCClient', FakeClient()),
        google_api_key=None,
        openai_api_key=None,
        venice_api_key=venice_api_key,
        selector='state.assistant.selected_image_generator',
    )


async def test_venice_generator_wired_to_venice_base_url() -> None:
    """A Venice key wires an OpenAI-compatible generator at Venice's base URL."""
    service = _build('venice-test-key-0123456789')
    try:
        venice = service.venice_image_generator
        assert isinstance(venice, UboOpenAIImageGenService)
        assert VENICE_BASE_URL in str(venice._client.base_url)  # noqa: SLF001
    finally:
        await service.aiohttp_session.close()


async def test_venice_generator_absent_without_key() -> None:
    """No Venice key leaves the Venice generator unset."""
    service = _build(None)
    try:
        assert service.venice_image_generator is None
    finally:
        await service.aiohttp_session.close()
