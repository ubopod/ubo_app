"""Module for scanning QR codes using the camera."""

from __future__ import annotations

import asyncio
import datetime
import uuid
from asyncio import Future
from typing import TYPE_CHECKING, TypeAlias, overload

from typing_extensions import TypeVar

from ubo_app.store.main import dispatch, subscribe_event
from ubo_app.store.services.camera import (
    CameraBarcodeEvent,
    CameraStartViewfinderAction,
    CameraStopViewfinderEvent,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationActionItem,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.rgb_ring import RgbRingBlinkAction

if TYPE_CHECKING:
    from collections.abc import Callable

QrCodeGroupDict: TypeAlias = dict[str, str | None] | None


ReturnType = TypeVar('ReturnType', infer_variance=True)


@overload
async def qrcode_input(
    pattern: str,
    *,
    prompt: str | None = None,
    extra_information: str | None = None,
    title: str | None = None,
) -> tuple[str, QrCodeGroupDict]: ...
@overload
async def qrcode_input(
    pattern: str,
    *,
    prompt: str | None = None,
    extra_information: str | None = None,
    title: str | None = None,
    resolver: Callable[[str, QrCodeGroupDict], ReturnType],
) -> ReturnType: ...
async def qrcode_input(
    pattern: str,
    *,
    prompt: str | None = None,
    extra_information: str | None = None,
    title: str | None = None,
    resolver: Callable[[str, QrCodeGroupDict], ReturnType] | None = None,
) -> tuple[str, QrCodeGroupDict] | ReturnType:
    """Use the camera to scan a QR code."""
    prompt_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()

    if prompt:
        notification_future: Future[None] = loop.create_future()
        dispatch(
            NotificationsAddAction(
                notification=Notification(
                    id='qrcode',
                    icon='󰄀󰐲',
                    title='QR Code' if title is None else title,
                    content=f'[size=18dp]{prompt}[/size]',
                    display_type=NotificationDisplayType.STICKY,
                    is_read=True,
                    extra_information=extra_information,
                    expiry_date=datetime.datetime.now(tz=datetime.UTC),
                    color='#ffffff',
                    actions=[
                        NotificationActionItem(
                            action=lambda: loop.call_soon_threadsafe(
                                notification_future.set_result,
                                None,
                            )
                            and None,
                            icon='󰄀',
                            dismiss_notification=True,
                        ),
                    ],
                    dismissable=False,
                    dismiss_on_close=True,
                    on_close=lambda: loop.call_soon_threadsafe(
                        notification_future.cancel,
                    ),
                ),
            ),
        )

        await notification_future

    future: Future[tuple[str, QrCodeGroupDict]] = loop.create_future()

    def handle_barcode_event(event: CameraBarcodeEvent) -> None:
        if event.id == prompt_id:
            from kivy.utils import get_color_from_hex

            loop.call_soon_threadsafe(future.set_result, (event.code, event.group_dict))
            kivy_color = get_color_from_hex('#21E693')
            dispatch(
                RgbRingBlinkAction(
                    color=(
                        round(kivy_color[0] * 255),
                        round(kivy_color[1] * 255),
                        round(kivy_color[2] * 255),
                    ),
                    repetitions=1,
                    wait=200,
                ),
            )

    def handle_cancel(event: CameraStopViewfinderEvent) -> None:
        if event.id == prompt_id:
            loop.call_soon_threadsafe(future.cancel)

    subscribe_event(
        CameraBarcodeEvent,
        handle_barcode_event,
        keep_ref=False,
    )
    subscribe_event(
        CameraStopViewfinderEvent,
        handle_cancel,
    )
    dispatch(CameraStartViewfinderAction(id=prompt_id, pattern=pattern))

    result = await future

    if not resolver:
        return result

    return resolver(*result)
