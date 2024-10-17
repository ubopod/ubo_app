"""Imperative input."""

from __future__ import annotations

import asyncio
import uuid
from asyncio import Future
from typing import TYPE_CHECKING, TypeAlias, overload

from typing_extensions import TypeVar

from ubo_app.store.main import store
from ubo_app.store.operations import (
    InputCancelEvent,
    InputDemandAction,
    InputDescription,
    InputFieldDescription,
    InputProvideEvent,
)
from ubo_app.store.services.camera import CameraStopViewfinderEvent
from ubo_app.store.services.rgb_ring import RgbRingBlinkAction

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.services.notifications import NotificationExtraInformation

InputResultGroupDict: TypeAlias = dict[str, str | None] | None


ReturnType = TypeVar('ReturnType', infer_variance=True)


@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    extra_information: NotificationExtraInformation | None = None,
    title: str | None = None,
    pattern: str,
    fields: list[InputFieldDescription] | None = None,
) -> tuple[str, InputResultGroupDict]: ...
@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    extra_information: NotificationExtraInformation | None = None,
    title: str | None = None,
    fields: list[InputFieldDescription],
) -> tuple[str, InputResultGroupDict]: ...
@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    extra_information: NotificationExtraInformation | None = None,
    title: str | None = None,
    pattern: str,
    fields: list[InputFieldDescription] | None = None,
    resolver: Callable[[str, InputResultGroupDict], ReturnType],
) -> ReturnType: ...
@overload
async def ubo_input(
    *,
    prompt: str | None = None,
    extra_information: NotificationExtraInformation | None = None,
    title: str | None = None,
    fields: list[InputFieldDescription],
    resolver: Callable[[str, InputResultGroupDict], ReturnType],
) -> ReturnType: ...
async def ubo_input(  # noqa: PLR0913
    *,
    prompt: str | None = None,
    extra_information: NotificationExtraInformation | None = None,
    title: str | None = None,
    pattern: str | None = None,
    fields: list[InputFieldDescription] | None = None,
    resolver: Callable[[str, InputResultGroupDict], ReturnType] | None = None,
) -> tuple[str, InputResultGroupDict] | ReturnType:
    """Input the user in an imperative way."""
    prompt_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()

    subscriptions: set[Callable[[], None]] = set()
    future: Future[tuple[str, InputResultGroupDict]] = loop.create_future()

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
            description=InputDescription(
                title=title or 'Untitled input',
                prompt=prompt,
                extra_information=extra_information,
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
