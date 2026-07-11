"""gRPC-Web transport for the LVGL GUI client.

A drop-in, API-compatible alternative to :class:`ubo_bindings.client.UboRPCClient`
that speaks gRPC-Web over plain HTTP/1.1 through an Envoy proxy — the very same
``/grpc`` endpoint the web-UI uses — instead of native gRPC over HTTP/2.

The motivation is resource-constrained targets (eventually an ESP32 running this
client in C), where a full HTTP/2 gRPC stack is impractical but an HTTP client is
trivial. Only the *wire* layer differs: request and response bodies are the exact
same protobuf messages as the native path, so the existing betterproto bindings
are reused verbatim for (de)serialization. The framing lives in the
dependency-free, MCU-portable :mod:`grpc_web_frame` module.

This client mirrors the small surface of :class:`UboRPCClient` that the LVGL
``GUIClient`` depends on: ``event_loop``, ``close``, ``dispatch``,
``subscribe_event`` and ``store_service.subscribe_store``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, TypeVar

import httpx
from ubo_bindings.store.v1 import (
    DispatchActionRequest,
    DispatchActionResponse,
    SubscribeEventRequest,
    SubscribeEventResponse,
    SubscribeStoreRequest,
    SubscribeStoreResponse,
)

from ubo_lvgl_gui_client.grpc_web_frame import (
    GrpcWebFrameParser,
    encode_message,
    is_trailer,
    parse_trailer,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from betterproto import Message
    from ubo_bindings.ubo.v1 import Action, Event

ResponseT = TypeVar('ResponseT', bound='Message')

logger = logging.getLogger(__name__)

CONTENT_TYPE = 'application/grpc-web+proto'
_HEADERS = {
    'content-type': CONTENT_TYPE,
    'accept': CONTENT_TYPE,
    'x-grpc-web': '1',
    'x-user-agent': 'ubo-lvgl-gui-client/grpc-web',
}

DISPATCH_ACTION_PATH = '/store.v1.StoreService/DispatchAction'
SUBSCRIBE_EVENT_PATH = '/store.v1.StoreService/SubscribeEvent'
SUBSCRIBE_STORE_PATH = '/store.v1.StoreService/SubscribeStore'

# Reconnect policy for long-lived event subscriptions. Envoy resets idle
# server-streams after its `stream_idle_timeout` (5 min by default), so these
# streams must be re-established transparently rather than dying.
RECONNECT_INITIAL_DELAY = 0.2
RECONNECT_MAX_DELAY = 30.0
# A stream that stayed up at least this long before dropping is considered
# healthy (e.g. an idle-timeout reset), so its backoff is reset; only rapid
# repeated failures (server unreachable) keep backing off.
HEALTHY_STREAM_SECONDS = 5.0


class GrpcWebError(RuntimeError):
    """A gRPC-Web call returned a non-zero ``grpc-status`` trailer."""


def _check_status(trailers: dict[str, str]) -> None:
    status = trailers.get('grpc-status', '0')
    if status != '0':
        message = trailers.get('grpc-message', '')
        msg = f'gRPC-Web call failed (status={status}): {message}'
        raise GrpcWebError(msg)


class _StoreServiceAdapter:
    """Expose the subset of ``StoreServiceStub`` the LVGL client reaches into."""

    def __init__(self, client: WebUboRPCClient) -> None:
        self._client = client

    def subscribe_store(
        self,
        subscribe_store_request: SubscribeStoreRequest,
    ) -> AsyncIterator[SubscribeStoreResponse]:
        """Server-stream store updates for the request's selectors."""
        return self._client._stream(  # noqa: SLF001
            SUBSCRIBE_STORE_PATH,
            subscribe_store_request,
            SubscribeStoreResponse,
        )


class WebUboRPCClient:
    """gRPC-Web remote store, API-compatible with ``UboRPCClient``."""

    def __init__(self, base_url: str) -> None:
        """Bind to the Envoy ``/grpc`` base URL (e.g. ``http://host:50052/grpc``)."""
        self.base_url = base_url.rstrip('/')
        self.event_loop = asyncio.get_event_loop()
        # No read timeout: server-streaming responses are long-lived.
        self._http = httpx.AsyncClient(
            http2=False,
            timeout=httpx.Timeout(connect=5.0, read=None, write=5.0, pool=5.0),
        )
        self.store_service = _StoreServiceAdapter(self)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.event_loop.create_task(self._http.aclose())

    async def _unary(
        self,
        path: str,
        request: Message,
        response_type: type[ResponseT],
    ) -> ResponseT | None:
        body = encode_message(bytes(request))
        result: Message | None = None
        async with self._http.stream(
            'POST',
            self.base_url + path,
            content=body,
            headers=_HEADERS,
        ) as response:
            response.raise_for_status()
            parser = GrpcWebFrameParser()
            async for chunk in response.aiter_bytes():
                for flag, payload in parser.feed(chunk):
                    if is_trailer(flag):
                        _check_status(parse_trailer(payload))
                    else:
                        result = response_type.FromString(payload)
        return result

    async def _stream(
        self,
        path: str,
        request: Message,
        response_type: type[ResponseT],
    ) -> AsyncIterator[ResponseT]:
        body = encode_message(bytes(request))
        async with self._http.stream(
            'POST',
            self.base_url + path,
            content=body,
            headers=_HEADERS,
        ) as response:
            response.raise_for_status()
            parser = GrpcWebFrameParser()
            async for chunk in response.aiter_bytes():
                for flag, payload in parser.feed(chunk):
                    if is_trailer(flag):
                        _check_status(parse_trailer(payload))
                    else:
                        yield response_type.FromString(payload)

    def dispatch(self, *, action: Action) -> None:
        """Dispatch an action to the remote store (fire-and-forget)."""
        self.event_loop.create_task(
            self._unary(
                DISPATCH_ACTION_PATH,
                DispatchActionRequest(action=action),
                DispatchActionResponse,
            ),
        )

    def subscribe_event(
        self,
        event_type: Event,
        callback: Callable[[Event], None],
    ) -> Callable[[], None]:
        """Subscribe to the remote store's events; returns an unsubscribe fn.

        The stream is re-established with exponential backoff if it drops, so a
        normal Envoy idle-timeout reset is handled transparently instead of
        killing the subscription.
        """

        async def iterator() -> None:
            delay = RECONNECT_INITIAL_DELAY
            while True:
                started = self.event_loop.time()
                try:
                    async for response in self._stream(
                        SUBSCRIBE_EVENT_PATH,
                        SubscribeEventRequest(events=[event_type]),
                        SubscribeEventResponse,
                    ):
                        try:
                            callback(response.event)
                        except Exception:
                            logger.exception('Error in event subscription callback')
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        'event subscription dropped (%s); reconnecting in %.1fs',
                        exc,
                        delay,
                    )
                if self.event_loop.time() - started >= HEALTHY_STREAM_SECONDS:
                    delay = RECONNECT_INITIAL_DELAY
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)

        task = self.event_loop.create_task(iterator())

        def unsubscribe() -> None:
            task.cancel()

        return unsubscribe
