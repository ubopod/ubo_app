"""Tests for the ``run_device_command`` LLM tool (stage 2).

Stage 1 matches a voice shortcut locally, in core, and never reaches the LLM.
This tool is the fallback for a near-miss phrasing that did: the catalog of
shortcuts is handed to the LLM as one generic tool with an id enum, and calling
it dispatches the command back to the store over gRPC.

Covered here: building the schema from a catalog, parsing the catalog off the
autorun (which double-wraps a list inside a message), and the handler's dispatch.
"""

from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast
from unittest.mock import AsyncMock, MagicMock

from ubo_assistant.switch import UboSwitchService
from ubo_assistant.tools import DeviceCommand, create_ubo_standard_tools

if TYPE_CHECKING:
    from ubo_bindings.client import UboRPCClient

F = TypeVar('F', bound=Callable[..., object])

_LIGHTS = DeviceCommand(
    id='lights',
    label='Lights',
    sample_phrases=('turn on the lights', 'lights on'),
)
_TV = DeviceCommand(id='tv', label='TV', sample_phrases=())


class _FakeClient:
    """Client surface used by the device-command tests."""

    def __init__(self) -> None:
        self.dispatched: list[Any] = []

    def dispatch(self, *, action: object) -> None:
        self.dispatched.append(action)

    def autorun(self, selectors: list[str]) -> Callable[[F], F]:
        _ = selectors

        def decorator(function: F) -> F:
            return function

        return decorator


class _Switcher(UboSwitchService[Any]):
    """Concrete switcher exposing the catalog-parsing behaviour."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}
        super().__init__(
            client=cast('UboRPCClient', _FakeClient()),
            selector='state.test.selected',
        )


def _catalog(*descriptors: object) -> list[Any]:
    """Build the autorun payload: a wrapper whose ``items`` wraps the list."""
    return [MagicMock(items=MagicMock(items=list(descriptors)))]


def _descriptor(
    command_id: str,
    label: str,
    sample_phrases: list[str] | None = None,
) -> Any:  # noqa: ANN401
    return MagicMock(
        id=command_id,
        label=label,
        sample_phrases=sample_phrases if sample_phrases is not None else [],
    )


def _tool_names(tools: object) -> list[str]:
    return [tool.name for tool in cast('Any', tools).standard_tools]


def _run_device_command_tool(tools: object) -> Any:  # noqa: ANN401
    return next(
        tool
        for tool in cast('Any', tools).standard_tools
        if tool.name == 'run_device_command'
    )


class ToolSchemaTests(unittest.TestCase):
    """Building the tool schema from the catalog."""

    def test_tool_is_omitted_when_no_commands_are_configured(self) -> None:
        """An enum with no members is not a usable schema — drop the tool."""
        names = _tool_names(create_ubo_standard_tools())
        self.assertNotIn('run_device_command', names)  # noqa: PT009
        # The unconditional builtins are still there.
        self.assertIn('draw_image', names)  # noqa: PT009
        self.assertIn('get_image', names)  # noqa: PT009

    def test_tool_is_added_when_commands_exist(self) -> None:
        """The catalog becomes one tool whose enum is the command ids."""
        tools = create_ubo_standard_tools([_LIGHTS, _TV])
        self.assertIn('run_device_command', _tool_names(tools))  # noqa: PT009

        tool = _run_device_command_tool(tools)
        self.assertEqual(  # noqa: PT009
            tool.properties['command_id']['enum'],
            ['lights', 'tv'],
        )
        self.assertEqual(tool.required, ['command_id'])  # noqa: PT009

    def test_labels_and_sample_phrases_reach_the_description(self) -> None:
        """The LLM needs to know what each id *means* to pick between them."""
        tool = _run_device_command_tool(create_ubo_standard_tools([_LIGHTS, _TV]))
        self.assertIn('lights: Lights', tool.description)  # noqa: PT009
        self.assertIn('turn on the lights', tool.description)  # noqa: PT009
        # A command with no samples still gets listed.
        self.assertIn('tv: TV', tool.description)  # noqa: PT009


class CatalogAutorunTests(unittest.TestCase):
    """Parsing the catalog off the gRPC autorun."""

    def test_double_wrapped_items_are_unwrapped(self) -> None:
        """A list inside a gRPC message arrives as a wrapper around a wrapper."""
        switcher = _Switcher()
        switcher._process_device_commands_data(  # noqa: SLF001
            _catalog(
                _descriptor('lights', 'Lights', ['turn on the lights']),
                _descriptor('tv', 'TV'),
            ),
        )

        self.assertEqual(  # noqa: PT009
            switcher._device_commands,  # noqa: SLF001
            [
                DeviceCommand(
                    id='lights',
                    label='Lights',
                    sample_phrases=('turn on the lights',),
                ),
                DeviceCommand(id='tv', label='TV', sample_phrases=()),
            ],
        )

    def test_an_empty_catalog_clears_the_commands(self) -> None:
        """Removing the last shortcut takes the tool away again."""
        switcher = _Switcher()
        switcher._device_commands = [_LIGHTS]  # noqa: SLF001
        switcher._process_device_commands_data(_catalog())  # noqa: SLF001
        self.assertEqual(switcher._device_commands, [])  # noqa: PT009, SLF001

    def test_a_missing_wrapper_is_tolerated(self) -> None:
        """An unset message field arrives as ``None``, not an empty wrapper."""
        switcher = _Switcher()
        switcher._process_device_commands_data([MagicMock(items=None)])  # noqa: SLF001
        self.assertEqual(switcher._device_commands, [])  # noqa: PT009, SLF001

    def test_a_malformed_payload_does_not_raise(self) -> None:
        """A parse failure resets the catalog rather than killing the autorun."""
        switcher = _Switcher()
        switcher._device_commands = [_LIGHTS]  # noqa: SLF001
        switcher._process_device_commands_data([])  # noqa: SLF001
        self.assertEqual(switcher._device_commands, [])  # noqa: PT009, SLF001


class RunDeviceCommandHandlerTests(unittest.IsolatedAsyncioTestCase):
    """The handler dispatches the command back to the store."""

    def _service(self, commands: list[DeviceCommand]) -> Any:  # noqa: ANN401
        from ubo_assistant.ubo_llm import UboLLMService

        service = cast('Any', object.__new__(UboLLMService))
        service.client = _FakeClient()
        service._device_commands = commands  # noqa: SLF001
        return service

    async def test_known_command_is_dispatched(self) -> None:
        """The action goes out on the wire carrying the id the LLM chose."""
        service = self._service([_LIGHTS])
        params = MagicMock(
            arguments={'command_id': 'lights'},
            result_callback=AsyncMock(),
        )

        await service.run_device_command(params)

        self.assertEqual(len(service.client.dispatched), 1)  # noqa: PT009
        action = service.client.dispatched[0]
        self.assertEqual(  # noqa: PT009
            action.speech_recognition_run_command_action.command_id,
            'lights',
        )
        # Optimistic: reported as run as soon as it is on the wire.
        params.result_callback.assert_awaited_once()
        self.assertIn(  # noqa: PT009
            'Lights',
            params.result_callback.await_args.args[0],
        )

    async def test_unknown_command_is_not_dispatched(self) -> None:
        """An id the LLM invented is reported back, not sent to the store."""
        service = self._service([_LIGHTS])
        params = MagicMock(
            arguments={'command_id': 'nonexistent'},
            result_callback=AsyncMock(),
        )

        await service.run_device_command(params)

        self.assertEqual(service.client.dispatched, [])  # noqa: PT009
        params.result_callback.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
