# ruff: noqa: T201, FBT003
"""Benchmark gRPC serialization/deserialization hot paths.

Measures build_message (Python -> Proto), _pack_to_any (store subscriptions),
rebuild_object (Proto -> Python), casing function caching, and class lookup
performance.

Run::

    uv run python tests/grpc/bench_serialization.py

"""

from __future__ import annotations

import time

import betterproto

from ubo_app.rpc.object_to_message import build_message
from ubo_app.rpc.store_service import _pack_to_any
from ubo_app.store.core.types.events import ViewChangedEvent
from ubo_app.store.core.types.status_bar import (
    ProgressNotificationData,
    StatusBarData,
    StatusIconData,
)
from ubo_app.store.core.types.view_data import (
    ApplicationViewData,
    HomeViewData,
    MenuItemData,
    MenuViewData,
)


def _make_menu_items(n: int) -> tuple[MenuItemData | None, ...]:
    return tuple(
        MenuItemData(
            key=f'item-{i}',
            label=f'Menu Item {i}',
            icon=f'icon-{i % 10}',
            color='#ffffff',
            is_short=i % 3 == 0,
            action_id=f'service:action-{i}',
            background_color='#333333' if i % 2 else None,
        )
        for i in range(n)
    )


def _make_status_bar() -> StatusBarData:
    return StatusBarData(
        title='ubo-pod-abc123',
        progress_notifications=(
            ProgressNotificationData(
                id='docker:pull',
                progress=0.65,
                color='#00ff00',
            ),
            ProgressNotificationData(
                id='update:check',
                progress=None,
                color='#ffff00',
            ),
        ),
        clock='14:30',
        temperature=45.2,
        light_level=80.0,
        icons=(
            StatusIconData(symbol='icon-wifi', color='white'),
            StatusIconData(symbol='icon-bt', color='#4444ff'),
            StatusIconData(symbol='icon-eth', color='white'),
        ),
    )


# --- Payloads ---

_MENU_4 = ViewChangedEvent(
    view=MenuViewData(title='Settings', items=_make_menu_items(4), total_pages=2),
    status_bar=_make_status_bar(),
)
_MENU_10 = ViewChangedEvent(
    view=MenuViewData(
        title='WiFi',
        heading='Networks',
        sub_heading='Select',
        items=_make_menu_items(10),
        total_pages=3,
    ),
    status_bar=_make_status_bar(),
)
_HOME = ViewChangedEvent(
    view=HomeViewData(
        menu_items=tuple(
            MenuItemData(key=k, label=lbl, icon='icon', action_id=a)
            for k, lbl, a in [
                ('main', 'Main', 'core:main'),
                ('notif', 'Notif', 'core:notif'),
                ('power', 'Power', 'core:power'),
            ]
        ),
        cpu_percent=23.5,
        ram_percent=67.8,
        volume_level=0.75,
    ),
    status_bar=_make_status_bar(),
)
_APP = ViewChangedEvent(
    view=ApplicationViewData(
        application_id='test:custom-widget',
        extra_data={
            'width': 320,
            'height': 240,
            'mode': 'preview',
            'fps': 30.0,
            'on': True,
        },
    ),
    status_bar=_make_status_bar(),
)

_ITERATIONS = 3000
_WARMUP = 20


def _bench(label: str, fn: object, arg: object) -> float:
    import types

    assert isinstance(fn, types.FunctionType)
    for _ in range(_WARMUP):
        fn(arg)
    t0 = time.perf_counter()
    for _ in range(_ITERATIONS):
        fn(arg)
    us = (time.perf_counter() - t0) / _ITERATIONS * 1e6
    print(f'  {label:50s}  {us:8.1f} us/call')
    return us


def _bench_casing() -> None:
    import betterproto.casing

    from ubo_app.rpc.message_to_object import _snake_case
    from ubo_app.rpc.object_to_message import _pascal_case

    names = [
        'MenuViewData', 'StatusBarData', 'MenuItemData', 'ViewChangedEvent',
        'ProgressNotificationData', 'ApplicationViewData', 'HomeViewData',
        'NotificationViewData', 'StatusIconData', 'StackPushMenuAction',
    ]

    for n in names:
        _snake_case(n)
        _pascal_case(n)

    iters = 10000
    t0 = time.perf_counter()
    for _ in range(iters):
        for n in names:
            _snake_case(n)
    cached_us = (time.perf_counter() - t0) / iters * 1e6

    t0 = time.perf_counter()
    for _ in range(iters):
        for n in names:
            betterproto.casing.snake_case(n)
    uncached_us = (time.perf_counter() - t0) / iters * 1e6

    print(f'  {"snake_case x10 (LRU cached)":50s}  {cached_us:8.1f} us/call')
    print(f'  {"snake_case x10 (uncached)":50s}  {uncached_us:8.1f} us/call')
    print(f'  {"  -> speedup":50s}  {uncached_us / cached_us:8.1f}x')


def _bench_class_lookup() -> None:
    from ubo_app.rpc.message_to_object import (
        _class_cache,
        get_class,
    )
    from ubo_app.rpc.object_to_message import (
        _msg_class_cache,
    )
    from ubo_app.rpc.object_to_message import (
        get_class as get_class_out,
    )

    msg = build_message(_MENU_4)
    assert isinstance(msg, betterproto.Message)
    get_class(msg)
    _bench('get_class inbound (cached)', get_class, msg)

    _class_cache.clear()
    t0 = time.perf_counter()
    get_class(msg)
    print(
        f'  {"get_class inbound (cold, 1 call)":50s}'
        f'  {(time.perf_counter() - t0) * 1e6:8.1f} us',
    )

    obj = _MENU_4.view
    get_class_out(obj)
    _bench('get_class outbound (cached)', get_class_out, obj)

    _msg_class_cache.clear()
    t0 = time.perf_counter()
    get_class_out(obj)
    print(
        f'  {"get_class outbound (cold, 1 call)":50s}'
        f'  {(time.perf_counter() - t0) * 1e6:8.1f} us',
    )


def _bench_deserialize() -> None:
    from ubo_app.rpc.message_to_object import rebuild_object
    from ubo_app.store.core.types.actions import StackPushMenuAction

    action = StackPushMenuAction(menu_key='settings:network')
    msg = build_message(action)
    _bench('StackPushMenuAction (rebuild_object)', rebuild_object, msg)


if __name__ == '__main__':
    print('=' * 72)
    print('gRPC Serialization Benchmark')
    print('=' * 72)

    print('\n--- build_message (Python -> Proto) ---')
    _bench('ViewChangedEvent + MenuView (4 items)', build_message, _MENU_4)
    _bench('ViewChangedEvent + MenuView (10 items)', build_message, _MENU_10)
    _bench('ViewChangedEvent + HomeView (3 items)', build_message, _HOME)
    _bench('ViewChangedEvent + AppView (5 extra_data)', build_message, _APP)
    _bench('MenuViewData only (4 items)', build_message, _MENU_4.view)
    _bench('StatusBarData', build_message, _make_status_bar())
    _bench('Single MenuItemData', build_message, _make_menu_items(1)[0])

    print('\n--- rebuild_object (Proto -> Python) ---')
    _bench_deserialize()

    print('\n--- _pack_to_any (store subscriptions) ---')
    _bench('string primitive', _pack_to_any, 'hello world')
    _bench('int primitive', _pack_to_any, 42)
    _bench('bool primitive', _pack_to_any, True)
    _bench('None primitive', _pack_to_any, None)
    _bench('MenuViewData object', _pack_to_any, _MENU_4.view)

    print('\n--- Casing (snake_case / pascal_case) ---')
    _bench_casing()

    print('\n--- Class lookup (get_class) ---')
    _bench_class_lookup()

    print('\n' + '=' * 72)
