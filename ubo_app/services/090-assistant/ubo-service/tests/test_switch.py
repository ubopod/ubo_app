"""Tests for Ubo's Pipecat native service switch adapters."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar, cast

from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.llm_service import FunctionCallHandler, LLMService
from pipecat.services.settings import LLMSettings

from ubo_assistant.switch import UboSwitchService
from ubo_assistant.ubo_llm import GenericLLMProxy

if TYPE_CHECKING:
    from ubo_bindings.client import UboRPCClient

F = TypeVar('F', bound=Callable[..., object])


class FakeClient:
    """Minimal client surface used by switcher tests."""

    def dispatch(self, *, action: object) -> None:
        """Ignore dispatched assistance reports."""
        _ = action

    def autorun(self, selectors: list[str]) -> Callable[[F], F]:
        """Return a decorator without invoking it."""
        _ = selectors

        def decorator(function: F) -> F:
            return function

        return decorator


class RecordingProcessor(FrameProcessor):
    """Frame processor used as a switch target."""


class TestSwitchService(UboSwitchService[FrameProcessor]):
    """Concrete switcher for unit tests."""

    def __init__(self) -> None:
        """Initialize the test switcher."""
        self.alpha = RecordingProcessor(name='alpha')
        self.beta = RecordingProcessor(name='beta')
        self._services = {
            'alpha': self.alpha,
            'beta': self.beta,
        }
        super().__init__(
            client=cast('UboRPCClient', FakeClient()),
            selector='state.test.selected',
        )


class RecordingLLM(LLMService):
    """LLM fake that records function registrations."""

    def __init__(self) -> None:
        """Initialize the fake LLM."""
        super().__init__(settings=LLMSettings())
        self.registered_functions: list[str | None] = []

    def register_function(
        self,
        function_name: str | None,
        handler: FunctionCallHandler,
        *,
        cancel_on_interruption: bool = True,
        timeout_secs: float | None = None,
    ) -> None:
        """Record and delegate function registration."""
        self.registered_functions.append(function_name)
        super().register_function(
            function_name,
            handler,
            cancel_on_interruption=cancel_on_interruption,
            timeout_secs=timeout_secs,
        )


async def fake_function_handler(_params: object) -> None:
    """Handle a placeholder LLM function."""


class SwitchTests(unittest.IsolatedAsyncioTestCase):
    """Native switch adapter behavior."""

    async def test_noop_service_is_initially_active(self) -> None:
        """Switchers start on the no-op branch until the store selects a provider."""
        switcher = TestSwitchService()

        self.assertIs(  # noqa: PT009
            switcher.strategy.active_service,
            switcher._noop_service,  # noqa: SLF001
        )
        self.assertIsNone(switcher.selected_service)  # noqa: PT009

    async def test_valid_selection_uses_native_switch_frame(self) -> None:
        """Valid Ubo service ids switch to the mapped Pipecat service."""
        switcher = TestSwitchService()

        await switcher.set_selected_service('alpha')

        self.assertIs(switcher.strategy.active_service, switcher.alpha)  # noqa: PT009
        self.assertIs(switcher.selected_service, switcher.alpha)  # noqa: PT009
        self.assertEqual(switcher._current_service_id, 'alpha')  # noqa: PT009, SLF001

    async def test_unavailable_selection_targets_noop(self) -> None:
        """Unavailable selections do not leave the previous provider active."""
        switcher = TestSwitchService()
        await switcher.set_selected_service('alpha')

        await switcher.set_selected_service('missing')

        self.assertIs(  # noqa: PT009
            switcher.strategy.active_service,
            switcher._noop_service,  # noqa: SLF001
        )
        self.assertIsNone(switcher.selected_service)  # noqa: PT009
        self.assertIsNone(switcher._current_service_id)  # noqa: PT009, SLF001

    async def test_generic_llm_proxy_replays_registered_functions(self) -> None:
        """A refreshed generic LLM receives functions registered on the proxy."""
        proxy = GenericLLMProxy()
        llm = RecordingLLM()

        proxy.register_function('draw_image', fake_function_handler)
        await proxy.set_service(llm)

        self.assertEqual(llm.registered_functions, ['draw_image'])  # noqa: PT009
        self.assertIs(proxy.service, llm)  # noqa: PT009


if __name__ == '__main__':
    unittest.main()
