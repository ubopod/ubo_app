"""Protocol-level round-trip for the MCU raw-TCP listener ("tcp-lite").

Boots the real core (gRPC server + the new ``mcu_server`` raw-TCP listener) via
``app_context``, then talks to ``MCU_LISTEN_PORT`` directly with
``asyncio.open_connection`` — no C client involved. Uses the frame encode/decode
helpers from ``ubo_app.rpc.mcu_server`` (already unit-tested in
``tests/grpc/test_mcu_frame.py``) to build request frames and parse response
frames, round-tripping one ``DispatchAction`` and one ``SubscribeStore``
delivery. No external creds/network needed, so this runs by default.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from tenacity import AsyncRetrying, stop_after_attempt, stop_after_delay, wait_fixed

if TYPE_CHECKING:
    from redux_pytest.fixtures import WaitFor

    from tests.fixtures import AppContext


async def _connect_with_retry(
    host: str,
    port: int,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open a TCP connection, retrying while the listener finishes booting.

    ``app_context.set_app()`` schedules ``mcu_serve()`` onto the worker
    thread's event loop via ``run_coroutine`` and returns immediately, so the
    listening socket may not exist yet the instant this test starts dialing.
    """
    async for attempt in AsyncRetrying(
        stop=stop_after_delay(5),
        wait=wait_fixed(0.1),
        reraise=True,
    ):
        with attempt:
            return await asyncio.open_connection(host, port)
    msg = 'unreachable'  # AsyncRetrying always returns or raises above
    raise AssertionError(msg)


async def test_mcu_server_roundtrip(
    app_context: AppContext,
    wait_for: WaitFor,
) -> None:
    """Round-trip a DispatchAction and a SubscribeStore delivery over tcp-lite."""
    app_context.set_app()

    @wait_for(run_async=True, stop=stop_after_attempt(5), wait=wait_fixed(1))
    def stack_is_loaded() -> None:
        from ubo_app.store.main import store

        state = store._state  # noqa: SLF001
        assert state is not None
        assert len(state.main.stack) > 0, 'Menu stack not loaded yet'

    await stack_is_loaded()

    # --- DispatchAction ---------------------------------------------------
    from typing import Any, cast

    import ubo_bindings.ubo.v1
    from betterproto.casing import snake_case
    from ubo_bindings.store.v1 import DispatchActionRequest, DispatchActionResponse

    from ubo_app.constants import MCU_LISTEN_PORT
    from ubo_app.rpc.mcu_server import (
        DISPATCH_ACTION_REQUEST,
        DISPATCH_ACTION_RESPONSE,
        SUBSCRIBE_STORE_REQUEST,
        SUBSCRIBE_STORE_RESPONSE,
        _encode_frame,
        _read_frame,
    )
    from ubo_app.rpc.object_to_message import build_message
    from ubo_app.store.services.keypad import Key, KeypadKeyPressAction

    action = KeypadKeyPressAction(key=Key.L1, pressed_keys=(Key.L1,))
    proto_msg = cast('Any', build_message(action))
    field_name = snake_case(type(action).__name__)
    wrapped = ubo_bindings.ubo.v1.Action(**{field_name: proto_msg})
    dispatch_request = DispatchActionRequest(action=wrapped)

    dispatch_reader, dispatch_writer = await _connect_with_retry(
        '127.0.0.1',
        MCU_LISTEN_PORT,
    )
    try:
        dispatch_writer.write(
            _encode_frame(
                DISPATCH_ACTION_REQUEST,
                dispatch_request.SerializeToString(),
            ),
        )
        await dispatch_writer.drain()

        message_type, payload = await _read_frame(dispatch_reader)
        assert message_type == DISPATCH_ACTION_RESPONSE
        DispatchActionResponse().parse(payload)
        # A single key-press action alone doesn't drive full menu navigation
        # (that needs a press+release cycle through the keypad reducer), so
        # the response frame parsing cleanly is the only guaranteed
        # observable here — the SubscribeStore round-trip below is what
        # confirms the store is live and producing real state.
    finally:
        dispatch_writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await dispatch_writer.wait_closed()

    # --- SubscribeStore -----------------------------------------------------
    from ubo_bindings.store.v1 import SubscribeStoreRequest, SubscribeStoreResponse

    subscribe_request = SubscribeStoreRequest(selectors=['state.main.current_view'])

    subscribe_reader, subscribe_writer = await _connect_with_retry(
        '127.0.0.1',
        MCU_LISTEN_PORT,
    )
    try:
        subscribe_writer.write(
            _encode_frame(
                SUBSCRIBE_STORE_REQUEST,
                subscribe_request.SerializeToString(),
            ),
        )
        await subscribe_writer.drain()

        message_type, payload = await _read_frame(subscribe_reader)
        assert message_type == SUBSCRIBE_STORE_RESPONSE
        response = SubscribeStoreResponse().parse(payload)
        assert len(response.results) == 1
        assert response.results[0].type_url.endswith('ViewData')
    finally:
        subscribe_writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await subscribe_writer.wait_closed()
