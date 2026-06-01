"""Headless demo: drive libubo_lvgl from Python via the bridge and snapshot.

Run: python -m ubo_lvgl_gui_client.demo [out.bmp]
Proves the CFFI bridge can render every view without gRPC or a display.
"""

from __future__ import annotations

import sys

from ubo_lvgl_gui_client.bridge import (
    BACKEND_BUFFER,
    HomeView,
    MenuItem,
    MenuView,
    Renderer,
    StatusBar,
)


def main() -> None:
    """Render a sample view to a BMP via the bridge."""
    out = sys.argv[1] if len(sys.argv) > 1 else '/tmp/ubo_py.bmp'  # noqa: S108
    view = sys.argv[2] if len(sys.argv) > 2 else 'menu'  # noqa: PLR2004

    r = Renderer()
    r.init(BACKEND_BUFFER, 240, 240)
    r.set_status_bar(StatusBar(title='ubo-r', clock='09:41', temperature=42))

    if view == 'home':
        r.render_home(HomeView(cpu_percent=37, ram_percent=64, volume_level=0.5))
    else:
        r.render_menu(
            MenuView(
                title='Python',
                items=[
                    MenuItem(
                        label='WiFi',
                        icon='\U000f05a9',
                        is_selected=True,
                        background_color='#1a1a1a',
                    ),
                    MenuItem(
                        label='Sound', icon='\U000f057e', background_color='#1a1a1a',
                    ),
                    MenuItem(
                        label='Apps', icon='\U000f0493', background_color='#1a1a1a',
                    ),
                ],
                total_pages=1,
            ),
        )

    r.snapshot(out)
    print(f'wrote {out} ({view})')  # noqa: T201


if __name__ == '__main__':
    main()
