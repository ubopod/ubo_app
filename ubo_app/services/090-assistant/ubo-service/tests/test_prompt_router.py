"""Tests for per-prompt LLM routing (``PromptRouter`` + ``UboLLMService.route_to``)."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, TypeVar, cast
from unittest.mock import AsyncMock, patch

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_context import NOT_GIVEN, LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings
from pipecat.tests.utils import SleepFrame, run_test

from ubo_assistant.prompt_router import (
    PromptRouter,
    RoutingDecision,
    RoutingRequest,
    latest_user_text,
)
from ubo_assistant.switch import _set_system_message_and_tools
from ubo_assistant.ubo_llm import (
    _DEFAULT_MODELS,
    AUTO_SERVICE_ID,
    LLMServiceConfig,
    UboLLMService,
)

if TYPE_CHECKING:
    from pipecat.processors.aggregators.llm_context import LLMContextMessage
    from ubo_bindings.client import UboRPCClient

F = TypeVar('F', bound=Callable[..., object])


def _context(*messages: LLMContextMessage) -> LLMContext:
    return LLMContext(list(messages))


def _user_turn(text: str = 'hello') -> LLMContext:
    return _context(
        {'role': 'system', 'content': 'system'},
        {'role': 'user', 'content': text},
    )


# --- Router ------------------------------------------------------------------


class FakeTarget:
    """Records what the router asked the switcher to do."""

    def __init__(self, *, enabled: bool = True) -> None:
        """Initialize the fake target."""
        self.enabled = enabled
        self.routes: list[RoutingDecision | None] = []
        self.events: list[str] = []

    @property
    def is_routing_enabled(self) -> bool:
        """Whether routing is on."""
        return self.enabled

    def routing_candidates(self) -> tuple[str, ...]:
        """Two fake providers."""
        return ('ollama', 'anthropic')

    async def route_to(
        self,
        decision: RoutingDecision | None,
        *,
        context: LLMContext,
    ) -> None:
        """Record the decision."""
        _ = context
        self.routes.append(decision)
        self.events.append('routed')


class StaticClassifier:
    """Always returns the same decision, recording each request."""

    def __init__(self, decision: RoutingDecision | None) -> None:
        """Initialize with a fixed decision."""
        self.decision = decision
        self.requests: list[RoutingRequest] = []
        self.warm_ups = 0

    async def warm_up(self) -> None:
        """Count warm-ups."""
        self.warm_ups += 1

    async def classify(self, request: RoutingRequest) -> RoutingDecision | None:
        """Return the fixed decision."""
        self.requests.append(request)
        return self.decision


class RaisingClassifier:
    """A classifier that fails."""

    async def warm_up(self) -> None:
        """Nothing to load."""

    async def classify(self, request: RoutingRequest) -> RoutingDecision | None:
        """Raise."""
        _ = request
        msg = 'classifier down'
        raise RuntimeError(msg)


class BlockingClassifier:
    """A classifier that never answers."""

    async def warm_up(self) -> None:
        """Nothing to load."""

    async def classify(self, request: RoutingRequest) -> RoutingDecision | None:
        """Block forever."""
        _ = request
        await asyncio.Event().wait()
        return None


async def _process(
    router: PromptRouter,
    target: FakeTarget,
    frame: Frame,
    direction: FrameDirection = FrameDirection.DOWNSTREAM,
) -> list[Frame]:
    """Run one frame through the router without a pipeline."""
    pushed: list[Frame] = []

    def record(frame: Frame, _direction: FrameDirection) -> None:
        pushed.append(frame)
        target.events.append('pushed')

    with (
        patch.object(PromptRouter.__mro__[1], 'process_frame', new=AsyncMock()),
        patch.object(router, 'push_frame', new=AsyncMock(side_effect=record)),
    ):
        await router.process_frame(frame, direction)
    return pushed


ANTHROPIC = RoutingDecision(provider_id='anthropic', model='claude-x')


class PromptRouterTests(unittest.IsolatedAsyncioTestCase):
    """``PromptRouter`` frame handling."""

    async def test_routes_before_releasing_the_prompt(self) -> None:
        """The switch happens before the context frame moves on."""
        target = FakeTarget()
        classifier = StaticClassifier(ANTHROPIC)
        router = PromptRouter(target=target, classifier=classifier)
        frame = LLMContextFrame(context=_user_turn('write a poem'))

        pushed = await _process(router, target, frame)

        self.assertEqual(pushed, [frame])  # noqa: PT009
        self.assertEqual(target.routes, [ANTHROPIC])  # noqa: PT009
        self.assertEqual(target.events, ['routed', 'pushed'])  # noqa: PT009
        self.assertEqual(classifier.requests[0].text, 'write a poem')  # noqa: PT009
        self.assertEqual(  # noqa: PT009
            classifier.requests[0].candidates,
            ('ollama', 'anthropic'),
        )

    async def test_pass_through_when_routing_disabled(self) -> None:
        """A concrete provider selection leaves the router inert."""
        target = FakeTarget(enabled=False)
        classifier = StaticClassifier(ANTHROPIC)
        router = PromptRouter(target=target, classifier=classifier)
        frame = LLMContextFrame(context=_user_turn())

        pushed = await _process(router, target, frame)

        self.assertEqual(pushed, [frame])  # noqa: PT009
        self.assertEqual(classifier.requests, [])  # noqa: PT009
        self.assertEqual(target.routes, [])  # noqa: PT009

    async def test_upstream_context_frame_is_not_routed(self) -> None:
        """Tool-result follow-ups arrive upstream and stay on their provider."""
        target = FakeTarget()
        classifier = StaticClassifier(ANTHROPIC)
        router = PromptRouter(target=target, classifier=classifier)
        frame = LLMContextFrame(context=_user_turn())

        pushed = await _process(router, target, frame, FrameDirection.UPSTREAM)

        self.assertEqual(pushed, [frame])  # noqa: PT009
        self.assertEqual(target.routes, [])  # noqa: PT009

    async def test_non_user_last_message_is_not_routed(self) -> None:
        """A context ending in a tool result is not re-classified."""
        target = FakeTarget()
        classifier = StaticClassifier(ANTHROPIC)
        router = PromptRouter(target=target, classifier=classifier)
        context = _context(
            {'role': 'user', 'content': 'weather?'},
            {'role': 'tool', 'content': 'sunny', 'tool_call_id': 'call-1'},
        )

        await _process(router, target, LLMContextFrame(context=context))

        self.assertEqual(target.routes, [])  # noqa: PT009

    async def test_classifier_failure_routes_to_fallback(self) -> None:
        """A failing classifier still lets the prompt through, on the fallback."""
        target = FakeTarget()
        router = PromptRouter(target=target, classifier=RaisingClassifier())
        frame = LLMContextFrame(context=_user_turn())

        pushed = await _process(router, target, frame)

        self.assertEqual(pushed, [frame])  # noqa: PT009
        self.assertEqual(target.routes, [None])  # noqa: PT009

    async def test_classifier_timeout_routes_to_fallback(self) -> None:
        """A slow classifier is cut off and the fallback is used."""
        target = FakeTarget()
        router = PromptRouter(
            target=target,
            classifier=BlockingClassifier(),
            timeout_secs=0.01,
        )
        frame = LLMContextFrame(context=_user_turn())

        pushed = await _process(router, target, frame)

        self.assertEqual(pushed, [frame])  # noqa: PT009
        self.assertEqual(target.routes, [None])  # noqa: PT009

    async def test_routing_failure_still_releases_the_prompt(self) -> None:
        """An error while switching doesn't swallow the user's turn."""
        target = FakeTarget()
        target.route_to = AsyncMock(side_effect=RuntimeError('switch failed'))  # type: ignore[method-assign]
        router = PromptRouter(target=target, classifier=StaticClassifier(ANTHROPIC))
        frame = LLMContextFrame(context=_user_turn())

        pushed = await _process(router, target, frame)

        self.assertEqual(pushed, [frame])  # noqa: PT009

    async def test_interruption_drops_the_held_prompt(self) -> None:
        """A barge-in while classifying cancels the turn; it never reaches the LLM."""
        target = FakeTarget()
        router = PromptRouter(target=target, classifier=BlockingClassifier())

        down, _up = await run_test(
            router,
            frames_to_send=[
                LLMContextFrame(context=_user_turn()),
                SleepFrame(sleep=0.1),
                InterruptionFrame(),
            ],
        )

        self.assertFalse(  # noqa: PT009
            any(isinstance(frame, LLMContextFrame) for frame in down),
        )
        self.assertEqual(target.routes, [])  # noqa: PT009

    async def test_speech_start_warms_up_once_when_enabled(self) -> None:
        """The classifier loads its models when the user first starts speaking."""
        target = FakeTarget()
        classifier = StaticClassifier(None)
        router = PromptRouter(target=target, classifier=classifier)

        with patch.object(router, 'create_task', side_effect=asyncio.ensure_future):
            await _process(router, target, UserStartedSpeakingFrame())
            await _process(router, target, UserStartedSpeakingFrame())
            await asyncio.sleep(0)

        self.assertEqual(classifier.warm_ups, 1)  # noqa: PT009

    async def test_no_warm_up_when_routing_disabled(self) -> None:
        """A concrete provider selection never loads the classifier."""
        target = FakeTarget(enabled=False)
        classifier = StaticClassifier(None)
        router = PromptRouter(target=target, classifier=classifier)

        with patch.object(router, 'create_task', side_effect=asyncio.ensure_future):
            await _process(router, target, UserStartedSpeakingFrame())
            await asyncio.sleep(0)

        self.assertEqual(classifier.warm_ups, 0)  # noqa: PT009

    def test_latest_user_text_joins_text_parts(self) -> None:
        """Multimodal user content yields only its text."""
        context = _context(
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'what is this'},
                    {'type': 'image_url', 'image_url': {'url': 'data:,'}},
                ],
            },
        )

        self.assertEqual(latest_user_text(context), 'what is this')  # noqa: PT009


# --- Switcher ----------------------------------------------------------------


class FakeClient:
    """Minimal client surface used by UboLLMService construction."""

    def __init__(self) -> None:
        """Record dispatched actions."""
        self.actions: list[object] = []

    def dispatch(self, *, action: object) -> None:
        """Record dispatched actions."""
        self.actions.append(action)

    def autorun(self, selectors: list[str]) -> Callable[[F], F]:
        """Return a decorator without invoking it."""
        _ = selectors

        def decorator(function: F) -> F:
            return function

        return decorator


class FakeLLM(LLMService):
    """Stand-in for a real provider service."""

    def __init__(self) -> None:
        """Initialize the fake LLM."""
        super().__init__(settings=LLMSettings())


class RoutedServiceCase(unittest.IsolatedAsyncioTestCase):
    """A ``UboLLMService`` on AUTO, with provider builds and tool updates faked."""

    async def asyncSetUp(self) -> None:
        """Build a service on AUTO with ``ollama`` as the fallback."""
        self.client = FakeClient()
        self.service = UboLLMService(
            client=cast('UboRPCClient', self.client),
            config=LLMServiceConfig(),
            selector='state.assistant.selected_llm',
        )
        self.refreshes: list[tuple[str, str | None]] = []
        self.unbuildable: set[str] = set()
        self.tool_updates: list[tuple[str, LLMContext | None]] = []
        self.tool_update_addenda: list[str] = []

        async def fake_refresh(service_id: str) -> None:
            model = (
                self.service._resolve_model(service_id)  # noqa: SLF001
                if service_id in _DEFAULT_MODELS
                else None
            )
            self.refreshes.append((service_id, model))
            if service_id in self.unbuildable:
                return
            proxy = self.service.service_map[service_id]
            if getattr(proxy, 'service', True) is None:
                await proxy.set_service(FakeLLM())  # type: ignore[attr-defined]

        async def fake_update_llm_tools(
            *,
            service_id: str,
            llm_service: LLMService,
            context: LLMContext | None = None,
            system_addendum: str = '',
        ) -> None:
            _ = llm_service
            self.tool_updates.append((service_id, context))
            self.tool_update_addenda.append(system_addendum)

        self.service._refresh_service = fake_refresh  # type: ignore[method-assign]  # noqa: SLF001
        self.service._update_llm_tools = fake_update_llm_tools  # type: ignore[method-assign]  # noqa: SLF001
        self.service._auto_fallback_id = 'ollama'  # noqa: SLF001
        await self.service.set_selected_service(AUTO_SERVICE_ID)
        self.refreshes.clear()

    def _active_id(self) -> str | None:
        return self.service._current_service_id  # noqa: SLF001


class RouteToTests(RoutedServiceCase):
    """``UboLLMService`` routing behavior."""

    async def test_auto_starts_on_the_fallback(self) -> None:
        """Selecting AUTO turns routing on and activates the fallback."""
        self.assertTrue(self.service.is_routing_enabled)  # noqa: PT009
        self.assertEqual(self._active_id(), 'ollama')  # noqa: PT009

    async def test_auto_waits_for_the_fallback(self) -> None:
        """Without a fallback yet, AUTO selects nothing and routing stays off."""
        service = UboLLMService(
            client=cast('UboRPCClient', FakeClient()),
            config=LLMServiceConfig(),
            selector='state.assistant.selected_llm',
        )

        await service.set_selected_service(AUTO_SERVICE_ID)

        self.assertFalse(service.is_routing_enabled)  # noqa: PT009
        self.assertIsNone(service._current_service_id)  # noqa: SLF001, PT009

    async def test_concrete_selection_turns_routing_off(self) -> None:
        """Picking a real provider disables routing."""
        await self.service.set_selected_service('openai')

        self.assertFalse(self.service.is_routing_enabled)  # noqa: PT009

    async def test_routes_to_the_decided_provider_and_model(self) -> None:
        """The decision's provider becomes active, built with its model."""
        context = _user_turn()

        await self.service.route_to(ANTHROPIC, context=context)

        self.assertEqual(self._active_id(), 'anthropic')  # noqa: PT009
        self.assertEqual(self.refreshes, [('anthropic', 'claude-x')])  # noqa: PT009
        self.assertEqual(self.tool_updates, [('anthropic', context)])  # noqa: PT009

    async def test_routing_never_writes_the_store(self) -> None:
        """Routing is transient: no action reaches the store."""
        self.client.actions.clear()

        await self.service.route_to(ANTHROPIC, context=_user_turn())

        self.assertEqual(self.client.actions, [])  # noqa: PT009
        self.assertNotIn('anthropic', self.service._config.selected_models)  # noqa: SLF001, PT009

    async def test_routed_switch_skips_the_history_wiping_refresh(self) -> None:
        """The switch itself must not queue the frame-based tools refresh."""
        self.service._processor_setup = cast('FrameProcessorSetup', object())  # noqa: SLF001
        scheduled: list[Coroutine[object, object, object]] = []

        def record_task(coro: Coroutine[object, object, object]) -> None:
            scheduled.append(coro)
            coro.close()

        self.service.create_task = record_task  # type: ignore[method-assign]

        await self.service.route_to(ANTHROPIC, context=_user_turn())

        self.assertEqual(scheduled, [])  # noqa: PT009

    async def test_none_routes_back_to_the_fallback(self) -> None:
        """No decision returns to the fallback with the user's model."""
        await self.service.route_to(ANTHROPIC, context=_user_turn())

        await self.service.route_to(None, context=_user_turn())

        self.assertEqual(self._active_id(), 'ollama')  # noqa: PT009
        self.assertEqual(  # noqa: PT009
            self.service._resolve_model('ollama'),  # noqa: SLF001
            _DEFAULT_MODELS['ollama'],
        )

    async def test_unknown_provider_routes_to_the_fallback(self) -> None:
        """A provider the switcher doesn't have falls back."""
        await self.service.route_to(
            RoutingDecision(provider_id='nope', model='x'),
            context=_user_turn(),
        )

        self.assertEqual(self._active_id(), 'ollama')  # noqa: PT009

    async def test_unbuildable_provider_routes_to_the_fallback(self) -> None:
        """A provider without credentials falls back."""
        self.unbuildable.add('grok')

        await self.service.route_to(
            RoutingDecision(provider_id='grok', model='grok-x'),
            context=_user_turn(),
        )

        self.assertEqual(self._active_id(), 'ollama')  # noqa: PT009

    async def test_repeat_route_does_not_rebuild(self) -> None:
        """Routing to the same provider/model again is free."""
        await self.service.route_to(ANTHROPIC, context=_user_turn())
        self.refreshes.clear()
        self.tool_updates.clear()

        await self.service.route_to(ANTHROPIC, context=_user_turn())

        self.assertEqual(self.refreshes, [])  # noqa: PT009
        self.assertEqual(self.tool_updates, [])  # noqa: PT009

    async def test_first_fallback_route_does_not_rebuild(self) -> None:
        """The fallback built when AUTO was selected is reused."""
        await self.service.route_to(None, context=_user_turn())

        self.assertEqual(self.refreshes, [])  # noqa: PT009

    async def test_model_change_on_active_provider_rebuilds_without_switch(
        self,
    ) -> None:
        """A new model for the active provider rebuilds it, tools untouched."""
        await self.service.route_to(ANTHROPIC, context=_user_turn())
        self.refreshes.clear()
        self.tool_updates.clear()

        await self.service.route_to(
            RoutingDecision(provider_id='anthropic', model='claude-y'),
            context=_user_turn(),
        )

        self.assertEqual(self.refreshes, [('anthropic', 'claude-y')])  # noqa: PT009
        self.assertEqual(self.tool_updates, [])  # noqa: PT009


class RouteToAddendumTests(RoutedServiceCase):
    """System-message addenda (domain profiles) in ``route_to``."""

    @staticmethod
    def _system_message(context: LLMContext) -> str:
        first = context.get_messages()[0]
        if not isinstance(first, dict) or first['role'] != 'system':
            msg = 'expected a system message first'
            raise AssertionError(msg)
        content = first['content']
        if not isinstance(content, str):
            msg = 'expected a text system message'
            raise TypeError(msg)
        return content

    async def test_switch_passes_the_addendum_to_the_tool_update(self) -> None:
        """A provider change composes the addendum into its system message."""
        await self.service.route_to(
            RoutingDecision('anthropic', 'claude-x', system_addendum='car profile'),
            context=_user_turn(),
        )

        self.assertEqual(self.tool_update_addenda, ['car profile'])  # noqa: PT009

    async def test_same_provider_new_addendum_rewrites_only_the_system_message(
        self,
    ) -> None:
        """Car and general share a model; switching domain swaps the profile."""
        context = _user_turn('when is the oil change due?')

        await self.service.route_to(
            RoutingDecision('ollama', 'gemma4:e2b', system_addendum='car profile'),
            context=context,
        )

        self.assertEqual(self.tool_updates, [])  # noqa: PT009
        message = self._system_message(context)
        self.assertTrue(message.endswith('\n\ncar profile'))  # noqa: PT009
        self.assertEqual(  # noqa: PT009
            context.get_messages()[-1],
            {'role': 'user', 'content': 'when is the oil change due?'},
        )

    async def test_same_addendum_leaves_the_context_alone(self) -> None:
        """A repeat domain doesn't touch the system message."""
        decision = RoutingDecision('ollama', 'gemma4:e2b', system_addendum='car')
        await self.service.route_to(decision, context=_user_turn())
        context = _user_turn()

        await self.service.route_to(decision, context=context)

        self.assertEqual(self._system_message(context), 'system')  # noqa: PT009

    async def test_fallback_drops_the_addendum(self) -> None:
        """Back on the fallback, the profile leaves the system message."""
        await self.service.route_to(
            RoutingDecision('ollama', 'gemma4:e2b', system_addendum='car profile'),
            context=_user_turn(),
        )
        context = _user_turn()

        await self.service.route_to(None, context=context)

        message = self._system_message(context)
        self.assertNotIn('car profile', message)  # noqa: PT009


    async def test_tools_refresh_makes_the_next_turn_reapply_the_addendum(
        self,
    ) -> None:
        """A system-prompt/MCP refresh drops the profile; the next turn restores it."""
        decision = RoutingDecision('ollama', 'gemma4:e2b', system_addendum='car')
        await self.service.route_to(decision, context=_user_turn())
        scheduled: list[Coroutine[object, object, object]] = []
        self.service.create_task = scheduled.append  # type: ignore[method-assign]
        self.service._refresh_active_llm_tools()  # noqa: SLF001
        for coro in scheduled:
            coro.close()
        context = _user_turn()

        await self.service.route_to(decision, context=context)

        self.assertTrue(self._system_message(context).endswith('\n\ncar'))  # noqa: PT009


class OnPremRoutingTests(unittest.IsolatedAsyncioTestCase):
    """The remote Ollama provider as a routing target."""

    @staticmethod
    def _service(url: str | None) -> UboLLMService:
        return UboLLMService(
            client=cast('UboRPCClient', FakeClient()),
            config=LLMServiceConfig(ollama_onprem_url=url),
            selector='state.assistant.selected_llm',
        )

    async def test_absent_without_url(self) -> None:
        """No on-prem URL: not a candidate, so the classifier picks a local target."""
        self.assertNotIn('ollama_onprem', self._service(None).routing_candidates())  # noqa: PT009

    async def test_builds_with_the_routed_model(self) -> None:
        """The decided model reaches the remote Ollama service."""
        service = self._service('http://remote:11434')
        service._update_llm_tools = AsyncMock()  # type: ignore[method-assign]  # noqa: SLF001
        service._auto_fallback_id = 'ollama'  # noqa: SLF001
        await service.set_selected_service(AUTO_SERVICE_ID)

        await service.route_to(
            RoutingDecision('ollama_onprem', 'medgemma-1.5:4b'),
            context=_user_turn(),
        )

        proxy = service.ollama_onprem_llm
        if proxy is None or proxy.service is None:
            self.fail('remote Ollama service was not built')
        self.assertEqual(proxy.service._settings.model, 'medgemma-1.5:4b')  # noqa: SLF001, PT009
        # What the routing logs report as the model in use.
        self.assertEqual(  # noqa: PT009
            service._built_model('ollama_onprem'),  # noqa: SLF001
            'medgemma-1.5:4b',
        )
        self.assertEqual(service._current_service_id, 'ollama_onprem')  # noqa: SLF001, PT009


class SystemMessageAndToolsTests(unittest.TestCase):
    """Applying a provider's tools to a held context."""

    def test_keeps_history_and_replaces_system_message(self) -> None:
        """Only the system message and tools change."""
        context = _context(
            {'role': 'system', 'content': 'old'},
            {'role': 'user', 'content': 'hi'},
            {'role': 'assistant', 'content': 'hello'},
            {'role': 'user', 'content': 'again'},
        )
        context.set_tools(
            ToolsSchema(
                standard_tools=[
                    FunctionSchema(
                        name='f',
                        description='d',
                        properties={},
                        required=[],
                    ),
                ],
            ),
        )

        _set_system_message_and_tools(context, system_message='new', tools=NOT_GIVEN)

        self.assertEqual(  # noqa: PT009
            context.get_messages(),
            [
                {'role': 'system', 'content': 'new'},
                {'role': 'user', 'content': 'hi'},
                {'role': 'assistant', 'content': 'hello'},
                {'role': 'user', 'content': 'again'},
            ],
        )
        self.assertIs(context.tools, NOT_GIVEN)  # noqa: PT009

    def test_inserts_system_message_when_missing(self) -> None:
        """A context without a system message gets one prepended."""
        context = _context({'role': 'user', 'content': 'hi'})

        _set_system_message_and_tools(context, system_message='new', tools=NOT_GIVEN)

        self.assertEqual(  # noqa: PT009
            context.get_messages(),
            [
                {'role': 'system', 'content': 'new'},
                {'role': 'user', 'content': 'hi'},
            ],
        )


if __name__ == '__main__':
    unittest.main()
