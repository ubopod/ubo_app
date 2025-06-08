"""Imperative input."""

from __future__ import annotations

import asyncio
import datetime
import functools
import inspect
from asyncio import Future
from dataclasses import replace
from typing import TYPE_CHECKING, cast, overload

from typing_extensions import TypeVar

from ubo_app.store.input.types import (
    InputCancelEvent,
    InputDemandAction,
    InputDescription,
    InputMethod,
    InputProvideEvent,
    InputResult,
)
from ubo_app.store.main import store
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.rgb_ring import RgbRingBlinkAction
from ubo_app.store.services.speech_synthesis import ReadableInformation

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


ReturnType = TypeVar('ReturnType', infer_variance=True)


METHOD_NAMES = {
    InputMethod.CAMERA: 'camera',
    InputMethod.WEB_DASHBOARD: 'web dashboard',
    InputMethod.PATH_SELECTOR: 'path selector',
}

METHOD_ICONS = {
    InputMethod.CAMERA: '󰄀',
    InputMethod.WEB_DASHBOARD: '󱋆',
    InputMethod.PATH_SELECTOR: '󰈤',
}


async def select_input_description(
    descriptions: Sequence[InputDescription],
) -> InputDescription | None:
    """Select the input method."""
    if len(descriptions) == 1:
        return descriptions[0]

    input_methods = [description.input_method for description in descriptions]

    if len(input_methods) == 1:
        return next(
            (
                description
                for description in descriptions
                if description.input_method == input_methods[0]
            ),
            None,
        )

    loop = asyncio.get_running_loop()
    input_method_future: Future[InputMethod] = loop.create_future()

    def set_result(method: InputMethod) -> None:
        loop.call_soon_threadsafe(input_method_future.set_result, method)

    if len(input_methods) == 2:  # noqa: PLR2004
        methods_as_text = f"""either {
            ' or '.join([METHOD_NAMES[method] for method in input_methods])
        }"""
    else:
        methods_as_text = f"""{
            ', '.join([METHOD_NAMES[method] for method in input_methods[:-1]])
        }, or {METHOD_NAMES[input_methods[-1]]}"""

    actions = [
        NotificationActionItem(
            key=METHOD_NAMES[method],
            icon=METHOD_ICONS[method],
            label=METHOD_NAMES[method].capitalize(),
            dismiss_notification=True,
            action=functools.partial(set_result, method),
        )
        for method in InputMethod
        if method in input_methods
    ]

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
                    text=f'You can use {methods_as_text} to '
                    'enter this input. Please choose one by pressing one of the '
                    'left buttons.',
                ),
                expiration_timestamp=datetime.datetime.now(tz=datetime.UTC),
                color='#ffffff',
                show_dismiss_action=False,
                dismiss_on_close=True,
                actions=actions,
                on_close=lambda: loop.call_soon_threadsafe(
                    input_method_future.cancel,
                ),
            ),
        ),
    )
    selected_input_method = await input_method_future
    return next(
        (
            description
            for description in descriptions
            if description.input_method == selected_input_method
        ),
        None,
    )


@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    title: str | None = None,
    descriptions: Sequence[InputDescription],
) -> tuple[str, InputResult]: ...
@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    title: str | None = None,
    descriptions: Sequence[InputDescription],
    resolver: Callable[[str, InputResult | None], ReturnType]
    | Callable[[str], ReturnType],
) -> ReturnType: ...
async def ubo_input(
    *,
    prompt: str | None = None,
    title: str | None = None,
    descriptions: Sequence[InputDescription],
    resolver: Callable[[str, InputResult | None], ReturnType]
    | Callable[[str], ReturnType]
    | None = None,
) -> tuple[str, InputResult | None] | ReturnType:
    """Input the user in an imperative way."""
    loop = asyncio.get_running_loop()

    descriptions = [
        replace(
            description,
            title=title if description.title is None else description.title,
            prompt=prompt if description.prompt is None else description.prompt,
        )
        for description in descriptions
    ]

    future: Future[tuple[str, InputResult | None]] = loop.create_future()

    selected_input_description = await select_input_description(descriptions)

    if selected_input_description is None:
        msg = 'No input description selected'
        raise asyncio.CancelledError(msg)

    def handle_input_cancel_event(event: InputCancelEvent) -> None:
        if event.id == selected_input_description.id:
            loop.call_soon_threadsafe(future.cancel)

    def handle_input_provide_event(event: InputProvideEvent) -> None:
        if event.id == selected_input_description.id:
            from kivy.utils import get_color_from_hex

            loop.call_soon_threadsafe(
                future.set_result,
                (event.value, event.result),
            )
            kivy_color = get_color_from_hex('#21E693')
            color = (
                round(kivy_color[0] * 255),
                round(kivy_color[1] * 255),
                round(kivy_color[2] * 255),
            )
            store.dispatch(
                RgbRingBlinkAction(
                    color=color,
                    repetitions=1,
                    wait=200,
                ),
            )

    store.subscribe_event(
        InputProvideEvent,
        handle_input_provide_event,
        keep_ref=False,
    )
    store.subscribe_event(
        InputCancelEvent,
        handle_input_cancel_event,
        keep_ref=False,
    )

    store.dispatch(InputDemandAction(description=selected_input_description))

    result = await future

    if not resolver:
        return result

    if len(inspect.signature(resolver).parameters) == 1:
        return cast('Callable[[str], ReturnType]', resolver)(result[0])

    return cast('Callable[[str, InputResult | None], ReturnType]', resolver)(*result)
