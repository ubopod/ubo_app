"""Imperative input."""

from __future__ import annotations

import asyncio
import datetime
import functools
import uuid
from asyncio import Future
from typing import TYPE_CHECKING, TypeAlias, overload

from typing_extensions import TypeVar

from ubo_app.store.input.types import (
    InputCancelEvent,
    InputDemandAction,
    InputDescription,
    InputFieldDescription,
    InputMethod,
    InputProvideEvent,
)
from ubo_app.store.main import store
from ubo_app.store.services.camera import CameraStopViewfinderEvent
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.rgb_ring import RgbRingBlinkAction
from ubo_app.store.services.voice import ReadableInformation

if TYPE_CHECKING:
    from collections.abc import Callable


InputResultGroupDict: TypeAlias = dict[str, str | None] | None


ReturnType = TypeVar('ReturnType', infer_variance=True)


METHOD_NAMES = {
    InputMethod.CAMERA: 'camera',
    InputMethod.WEB_DASHBOARD: 'web dashboard',
}

METHOD_ICONS = {
    InputMethod.CAMERA: '󰄀',
    InputMethod.WEB_DASHBOARD: '󱋆',
}


async def select_input_method(input_methods: InputMethod) -> InputMethod:
    """Select the input method."""
    if input_methods.value.bit_count() == 1:
        return input_methods
    loop = asyncio.get_running_loop()
    input_method_future: Future[InputMethod] = loop.create_future()

    def set_result(method: InputMethod) -> None:
        loop.call_soon_threadsafe(input_method_future.set_result, method)

    if len(input_methods) == 1:
        set_result(next(iter(input_methods)))
        return await input_method_future

    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id='input:method',
                icon='',
                title='Input method',
                content='Do you want to use the camera or the web dashboard?',
                display_type=NotificationDisplayType.STICKY,
                is_read=True,
                extra_information=ReadableInformation(
                    text='You can use either the camera or the web dashboard to '
                    'enter this input. Please choose one by pressing one of the '
                    'left buttons.',
                ),
                expiration_timestamp=datetime.datetime.now(tz=datetime.UTC),
                color='#ffffff',
                show_dismiss_action=False,
                dismiss_on_close=True,
                actions=[
                    NotificationActionItem(
                        key=METHOD_NAMES[method],
                        icon=METHOD_ICONS[method],
                        dismiss_notification=True,
                        action=functools.partial(set_result, method),
                    )
                    for method in InputMethod
                    if method in input_methods
                ],
                on_close=lambda: loop.call_soon_threadsafe(
                    input_method_future.cancel,
                ),
            ),
        ),
    )
    return await input_method_future


@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    qr_code_generation_instructions: ReadableInformation | None = None,
    title: str | None = None,
    pattern: str,
    fields: list[InputFieldDescription] | None = None,
    input_methods: InputMethod = InputMethod.ALL,
) -> tuple[str, InputResultGroupDict]: ...
@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    qr_code_generation_instructions: ReadableInformation | None = None,
    title: str | None = None,
    fields: list[InputFieldDescription],
    input_methods: InputMethod = InputMethod.ALL,
) -> tuple[str, InputResultGroupDict]: ...
@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    qr_code_generation_instructions: ReadableInformation | None = None,
    title: str | None = None,
    pattern: str,
    fields: list[InputFieldDescription] | None = None,
    resolver: Callable[[str, InputResultGroupDict], ReturnType],
    input_methods: InputMethod = InputMethod.ALL,
) -> ReturnType: ...
@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    qr_code_generation_instructions: ReadableInformation | None = None,
    title: str | None = None,
    fields: list[InputFieldDescription],
    resolver: Callable[[str, InputResultGroupDict], ReturnType],
    input_methods: InputMethod = InputMethod.ALL,
) -> ReturnType: ...
async def ubo_input(  # noqa: PLR0913
    *,
    prompt: str | None = None,
    qr_code_generation_instructions: ReadableInformation | None = None,
    title: str | None = None,
    pattern: str | None = None,
    fields: list[InputFieldDescription] | None = None,
    resolver: Callable[[str, InputResultGroupDict], ReturnType] | None = None,
    input_methods: InputMethod = InputMethod.ALL,
) -> tuple[str, InputResultGroupDict] | ReturnType:
    """Input the user in an imperative way."""
    prompt_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()

    subscriptions: set[Callable[[], None]] = set()
    future: Future[tuple[str, InputResultGroupDict]] = loop.create_future()

    selected_input_method = await select_input_method(input_methods)

    def unsubscribe() -> None:
        for subscription in subscriptions:
            subscription()

    def handle_input_cancel_event(event: InputCancelEvent) -> None:
        if event.id == prompt_id:
            unsubscribe()
            loop.call_soon_threadsafe(future.cancel)

    def handle_input_provide_event(event: InputProvideEvent) -> None:
        if event.id == prompt_id:
            unsubscribe()
            from kivy.utils import get_color_from_hex

            loop.call_soon_threadsafe(
                future.set_result,
                (event.value, event.data),
            )
            kivy_color = get_color_from_hex('#21E693')
            color = tuple(round(c * 255) for c in kivy_color[:3])
            store.dispatch(
                RgbRingBlinkAction(
                    color=color,
                    repetitions=1,
                    wait=200,
                ),
            )

    def handle_cancel(event: CameraStopViewfinderEvent) -> None:
        if event.id == prompt_id:
            unsubscribe()
            loop.call_soon_threadsafe(future.cancel)

    subscriptions.add(
        store.subscribe_event(
            InputProvideEvent,
            handle_input_provide_event,
            keep_ref=False,
        ),
    )
    subscriptions.add(
        store.subscribe_event(
            InputCancelEvent,
            handle_input_cancel_event,
            keep_ref=False,
        ),
    )

    subscriptions.add(
        store.subscribe_event(
            CameraStopViewfinderEvent,
            handle_cancel,
            keep_ref=False,
        ),
    )
    subscriptions.add(
        store.subscribe_event(
            CameraStopViewfinderEvent,
            handle_cancel,
            keep_ref=False,
        ),
    )

    store.dispatch(
        InputDemandAction(
            method=selected_input_method,
            description=InputDescription(
                title=title or 'Untitled input',
                prompt=prompt,
                extra_information=qr_code_generation_instructions
                if selected_input_method is InputMethod.CAMERA
                else None,
                id=prompt_id,
                pattern=pattern,
                fields=fields,
            ),
        ),
    )

    result = await future

    if not resolver:
        return result

    return resolver(*result)
