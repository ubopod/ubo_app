"""Fixtures for the application tests."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import sys
import weakref
from typing import TYPE_CHECKING

import pytest

from ubo_app.setup import setup

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from _pytest.fixtures import SubRequest

    from ubo_app.menu_app.menu import MenuApp

modules_snapshot = set(sys.modules)


class AppContext:
    """Context object for tests running a menu application."""

    def __init__(self: AppContext, request: SubRequest) -> None:
        """Initialize the context."""
        self.request = request

    def set_app(self: AppContext, app: MenuApp) -> None:
        """Set the application."""
        from ubo_app.utils.loop import setup_event_loop

        setup_event_loop()
        self.app = app
        loop = asyncio.get_event_loop()
        self.task = loop.create_task(self.app.async_run(async_lib='asyncio'))

    async def clean_up(self: AppContext) -> None:
        """Clean up the application."""
        assert hasattr(self, 'task'), 'App not set for test'

        self.app.stop()
        await self.task

        app_ref = weakref.ref(self.app)
        self.app.root.clear_widgets()

        await asyncio.sleep(0.5)
        del self.app
        del self.task

        gc.collect()
        app = app_ref()

        if app is not None and self.request.session.testsfailed == 0:
            logging.getLogger().debug(
                'Memory leak: failed to release app for test.\n'
                + json.dumps(
                    {
                        'refcount': sys.getrefcount(app),
                        'referrers': gc.get_referrers(app),
                        'ref': app_ref,
                    },
                    sort_keys=True,
                    indent=2,
                    default=str,
                ),
            )
            gc.collect()
            for cell in gc.get_referrers(app):
                if type(cell).__name__ == 'cell':
                    from ubo_app.utils.garbage_collection import examine

                    logging.getLogger().debug(
                        'CELL EXAMINATION\n' + json.dumps({'cell': cell}),
                    )
                    examine(cell, depth_limit=2)
            assert app is None, 'Memory leak: failed to release app for test'

        from kivy.core.window import Window

        Window.close()

        for module in set(sys.modules) - modules_snapshot:
            if module != 'objc' and 'numpy' not in module and 'cache' not in module:
                del sys.modules[module]
        gc.collect()


@pytest.fixture()
async def app_context(request: SubRequest) -> AsyncGenerator[AppContext, None]:
    """Create the application."""
    import os

    os.environ['KIVY_NO_FILELOG'] = '1'
    os.environ['KIVY_NO_CONSOLELOG'] = '1'
    os.environ['KIVY_METRICS_DENSITY'] = '1'

    setup()

    from kivy.lang.builder import Builder

    Builder.load_string("""
<-Slider>:
    canvas:
        Color:
            rgb: 0.6, 0.1, 0.1
        Rectangle:
            pos: (self.x, self.center_y - self.background_width/6) if self.orientation \
== 'horizontal' else (self.center_x - self.background_width/6, self.y)
            size: (self.width, self.background_width/3) if self.orientation == 'horizon\
tal' else (self.background_width/3, self.height)
        Color:
            rgb: 0.8, 0.3, 0.3
        RoundedRectangle:
            pos: (root.value_pos[0] - root.cursor_width*0.4, root.center_y - root.curso\
r_height*0.4) if root.orientation == 'horizontal' else (root.center_x - root.cursor_wid\
th*0.4, root.value_pos[1] - root.cursor_height*0.4)
            size: root.cursor_size[0] * 0.8, root.cursor_size[1] * 0.8
            radius: root.cursor_size[0] * 0.4, root.cursor_size[1] * 0.4
    """)

    import headless_kivy_pi.config

    headless_kivy_pi.config.setup_headless_kivy({'automatic_fps': True})

    context = AppContext(request)

    yield context

    await context.clean_up()

    assert not hasattr(context, 'app'), 'App not cleaned up'
