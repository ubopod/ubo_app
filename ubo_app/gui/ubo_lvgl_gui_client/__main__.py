"""Entry point for the LVGL GUI client.

Threading: LVGL/SDL owns the main thread (required by SDL on macOS); the gRPC
client runs its asyncio loop on a worker thread. View updates arrive on the gRPC
thread and call the renderer (which takes an internal lock). Key events arrive on
the main thread and are marshalled onto the gRPC loop via call_soon_threadsafe.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
from typing import Any

logger = logging.getLogger('ubo_lvgl_gui_client')


def _setup_logging(*, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                          datefmt='%H:%M:%S'),
    )
    logger.setLevel(level)
    logger.addHandler(handler)


def main() -> None:  # noqa: C901, PLR0915
    """Run the LVGL GUI client."""
    parser = argparse.ArgumentParser(description='Ubo LVGL GUI Client')
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=50051)
    parser.add_argument('--backend', choices=['sdl', 'st7789'], default='sdl')
    parser.add_argument('-v', '--verbose', action='store_true', default=False)
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)

    from ubo_lvgl_gui_client import view_translator
    from ubo_lvgl_gui_client.bridge import BACKEND_SDL, BACKEND_ST7789, Renderer
    from ubo_lvgl_gui_client.client import GUIClient
    from ubo_lvgl_gui_client.keyboard import build_action

    renderer = Renderer()
    backend = BACKEND_ST7789 if args.backend == 'st7789' else BACKEND_SDL
    renderer.init(backend, 240, 240)

    # Shared handles, populated by the gRPC thread.
    state: dict[str, Any] = {}

    def _update_frame_stream(view: object) -> None:
        """(Un)subscribe to a frame_stream view's live frames on view changes."""
        client = state.get('client')
        if client is None:
            return
        stream_id = view_translator.frame_stream_id(view)
        if stream_id == state.get('stream_id'):
            return
        unsubscribe = state.get('stream_unsub')
        if unsubscribe is not None:
            try:
                unsubscribe()
            except Exception:  # noqa: BLE001
                logger.debug('frame-stream unsubscribe failed', exc_info=True)
        state['stream_unsub'] = None
        state['stream_id'] = None
        if stream_id:
            def on_frame(data: bytes, width: int, height: int) -> None:
                try:
                    renderer.update_frame(data, width, height)
                except Exception:
                    logger.exception('frame update failed')

            state['stream_unsub'] = client.subscribe_frame_stream(
                stream_id, on_frame,
            )
            state['stream_id'] = stream_id

    def on_view(view: object, status_bar: object, is_blanked: object) -> None:
        try:
            if status_bar is not None:
                renderer.set_status_bar(view_translator.translate_status_bar(status_bar))
            view_translator.render_view(renderer, view)
            _update_frame_stream(view)
            if is_blanked is not None:
                renderer.set_blanked(bool(is_blanked))
        except Exception:
            logger.exception('Failed to render view %s', type(view).__name__)

    def _on_loop_exception(
        loop: asyncio.AbstractEventLoop,
        context: dict[str, Any],
    ) -> None:
        # Dispatching an action (e.g. a keypress) while the server is briefly
        # unreachable leaves an un-awaited task that raises a connection error.
        # That is benign — the subscription loop reconnects — so keep it quiet.
        exc = context.get('exception')
        if isinstance(exc, (OSError, ConnectionError)):
            logger.debug('dispatch failed (server unreachable): %s', exc)
            return
        loop.default_exception_handler(context)

    def grpc_thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(_on_loop_exception)
        state['loop'] = loop
        client = GUIClient(args.host, args.port)
        client.connect()
        state['client'] = client
        renderer.set_connected(True)
        client.subscribe_view_changes(
            on_view,
            on_connected=lambda: renderer.set_connected(True),
            on_disconnect=lambda delay, attempt, max_attempts: (
                renderer.set_disconnect_status(attempt, max_attempts, int(delay))
            ),
        )

        def on_screenshot() -> None:
            try:
                from ubo_bindings.ubo.v1 import Action, ScreenshotDataAction

                from ubo_lvgl_gui_client import screenshot

                png_bytes, digest = screenshot.capture(renderer)
                client.dispatch_raw(
                    Action(
                        screenshot_data_action=ScreenshotDataAction(
                            data=png_bytes, hash=digest,
                        ),
                    ),
                )
            except Exception:
                logger.exception('screenshot capture failed')

        client.subscribe_screenshot_events(on_screenshot)
        logger.info('gRPC client connected to %s:%d', args.host, args.port)
        loop.run_forever()

    threading.Thread(target=grpc_thread, daemon=True).start()

    def on_key(key: str, pressed: bool) -> None:  # noqa: FBT001
        if not pressed:
            return
        action = build_action(key)
        loop = state.get('loop')
        client = state.get('client')
        if action is not None and loop is not None and client is not None:
            loop.call_soon_threadsafe(client.dispatch_raw, action)

    renderer.set_input_callback(on_key)

    logger.info('Starting LVGL loop (backend=%s)', args.backend)
    renderer.run(threaded=False)  # blocks the main thread until the window closes


if __name__ == '__main__':
    main()
