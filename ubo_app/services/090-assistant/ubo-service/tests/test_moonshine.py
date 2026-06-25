"""Tests for :class:`MoonshineSTTProxy` selection / download / delete.

The proxy separates *selection* (load-only, never downloads) from explicit
*download* and *delete*. These tests mock the real service build (no network)
and the cache removal, and assert: selecting an un-downloaded model never
builds (so booting can't auto-download), downloading reports the spinner +
downloaded id and swaps in the active model, an in-flight download reconciles
to a newer selection, and deleting drops the cached model + the live service.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import betterproto

from ubo_assistant.moonshine import MoonshineSTTProxy


def _fake_service(model_id: str) -> AsyncMock:
    """Return an AsyncMock stand-in for a built MoonshineSTTService."""
    service = AsyncMock(name=f'MoonshineSTTService[{model_id}]')
    service.model_tag = model_id
    return service


def _dispatched(client: MagicMock) -> list[tuple[str, Any]]:
    """Return the (oneof-field, value) of every action dispatched on *client*."""
    return [
        betterproto.which_one_of(call.kwargs['action'], 'action')
        for call in client.dispatch.call_args_list
    ]


def _fields(client: MagicMock) -> list[str]:
    return [name for name, _ in _dispatched(client)]


class MoonshineProxyTests(unittest.IsolatedAsyncioTestCase):
    """Selection, download, delete, and reconciliation for MoonshineSTTProxy."""

    def _make(self) -> tuple[MoonshineSTTProxy, MagicMock]:
        client = MagicMock(name='UboRPCClient')
        proxy = MoonshineSTTProxy(client=client)
        proxy._loop = asyncio.get_running_loop()  # noqa: SLF001
        return proxy, client

    async def test_ensure_active_skips_undownloaded_model(self) -> None:
        """Selecting a not-downloaded model never builds (no auto-download)."""
        proxy, client = self._make()
        proxy._active_model_id = 'tiny'  # noqa: SLF001
        proxy._downloaded = set()  # noqa: SLF001

        with patch.object(proxy, '_build', new=AsyncMock()) as build:
            await proxy._ensure_active()  # noqa: SLF001

        build.assert_not_called()
        self.assertIsNone(proxy._loaded_model_id)  # noqa: PT009, SLF001
        client.dispatch.assert_not_called()

    async def test_ensure_active_loads_downloaded_model_from_cache(self) -> None:
        """A downloaded active model is built from cache and swapped in."""
        proxy, _ = self._make()
        proxy._active_model_id = 'tiny'  # noqa: SLF001
        proxy._downloaded = {'tiny'}  # noqa: SLF001

        with patch.object(
            proxy,
            '_build',
            new=AsyncMock(side_effect=lambda mid: _fake_service(mid)),
        ) as build:
            await proxy._ensure_active()  # noqa: SLF001

        build.assert_awaited_once_with('tiny')
        self.assertEqual(proxy._loaded_model_id, 'tiny')  # noqa: PT009, SLF001
        self.assertEqual(  # noqa: PT009
            cast('Any', proxy._service).model_tag,  # noqa: SLF001
            'tiny',
        )

    async def test_download_reports_and_swaps_active(self) -> None:
        """Downloading the active model reports spinner + id and swaps it in."""
        proxy, client = self._make()
        proxy._active_model_id = 'tiny'  # noqa: SLF001
        proxy._downloaded = set()  # noqa: SLF001

        with patch.object(
            proxy,
            '_build',
            new=AsyncMock(side_effect=lambda mid: _fake_service(mid)),
        ):
            await proxy._download('tiny')  # noqa: SLF001

        self.assertIn('tiny', proxy._downloaded)  # noqa: PT009, SLF001
        self.assertEqual(proxy._loaded_model_id, 'tiny')  # noqa: PT009, SLF001
        self.assertEqual(  # noqa: PT009
            _fields(client),
            [
                'assistant_set_moonshine_downloading_action',
                'assistant_add_moonshine_downloaded_model_action',
                'assistant_set_moonshine_downloading_action',
            ],
        )
        actions = _dispatched(client)
        self.assertEqual(actions[0][1].model_id, 'tiny')  # noqa: PT009
        self.assertEqual(actions[1][1].model_id, 'tiny')  # noqa: PT009
        self.assertEqual(actions[2][1].model_id, '')  # noqa: PT009

    async def test_download_reconciles_to_newer_selection(self) -> None:
        """A finished download for a no-longer-active model loads the active one.

        Guards the dropped-in-flight-change bug: if the user selects
        ``small-streaming`` while ``base`` is still downloading, the proxy must
        end up loaded on ``small-streaming`` (which is downloaded), not ``base``.
        """
        proxy, _ = self._make()
        proxy._downloaded = {'base', 'small-streaming'}  # noqa: SLF001
        proxy._active_model_id = 'small-streaming'  # noqa: SLF001

        with patch.object(
            proxy,
            '_build',
            new=AsyncMock(side_effect=lambda mid: _fake_service(mid)),
        ):
            await proxy._download('base')  # noqa: SLF001

        self.assertEqual(  # noqa: PT009
            proxy._loaded_model_id,  # noqa: SLF001
            'small-streaming',
        )
        self.assertEqual(  # noqa: PT009
            cast('Any', proxy._service).model_tag,  # noqa: SLF001
            'small-streaming',
        )

    async def test_delete_removes_cache_and_drops_loaded_service(self) -> None:
        """Deleting the loaded model removes the cache and clears the service."""
        proxy, client = self._make()
        proxy._downloaded = {'tiny'}  # noqa: SLF001
        proxy._loaded_model_id = 'tiny'  # noqa: SLF001
        proxy._service = _fake_service('tiny')  # noqa: SLF001

        with patch(
            'ubo_assistant.moonshine.remove_model',
        ) as remove_model:
            await proxy._delete('tiny')  # noqa: SLF001

        remove_model.assert_called_once_with('tiny')
        self.assertNotIn('tiny', proxy._downloaded)  # noqa: PT009, SLF001
        self.assertIsNone(proxy._service)  # noqa: PT009, SLF001
        self.assertIsNone(proxy._loaded_model_id)  # noqa: PT009, SLF001
        self.assertEqual(  # noqa: PT009
            _fields(client),
            ['assistant_remove_moonshine_downloaded_model_action'],
        )

    def test_request_helpers_ignore_empty_and_unchanged(self) -> None:
        """The foreign-thread entry points ignore empty / unchanged ids."""
        client = MagicMock(name='UboRPCClient')
        proxy = MoonshineSTTProxy(client=client, model_id='tiny')
        # No loop set: scheduling is a no-op, but state still updates.
        proxy.set_active_model('')
        self.assertEqual(proxy._active_model_id, 'tiny')  # noqa: PT009, SLF001
        proxy.set_active_model('tiny')
        self.assertEqual(proxy._active_model_id, 'tiny')  # noqa: PT009, SLF001
        proxy.set_active_model('base')
        self.assertEqual(proxy._active_model_id, 'base')  # noqa: PT009, SLF001
