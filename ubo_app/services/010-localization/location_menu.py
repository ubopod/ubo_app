"""Settings → Localization → Location.

Shows where the device thinks it is and where that came from. The detected
location can be corrected by hand (a Web UI form — no scrolling through
thousands of cities) or reset back to automatic IP detection.
"""

from __future__ import annotations

import asyncio
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action
from ubo_app.store.core.types import MenuItemData, UpdateDynamicMenuAction
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.localization import (
    LocalizationResetLocationAction,
    LocalizationSetLocationAction,
    LocationInfo,
    LocationSource,
)
from ubo_app.store.services.notifications import (
    Notification,
    NotificationsAddAction,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input

LOCATION_MENU_ID = 'localization:location-menu'
OPEN_LOCATION_ACTION_ID = 'localization:open_location_menu'
SET_LOCATION_ACTION_ID = 'localization:set_location_manually'
RESET_LOCATION_ACTION_ID = 'localization:reset_location'


def describe_location(
    location: LocationInfo | None,
    source: LocationSource,
) -> str:
    """One line telling the user where they are and who decided that."""
    if location is None:
        return 'Not detected yet'

    place = ', '.join(part for part in (location.city, location.country) if part)
    if not place:
        place = f'{location.latitude:.2f}, {location.longitude:.2f}'

    origin = (
        'set manually'
        if source is LocationSource.MANUAL
        else 'detected automatically'
    )
    return f'{place} — {origin}'


def _notify(title: str, content: str) -> None:
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(title=title, content=content),
        ),
    )


async def _location_form(location: LocationInfo | None) -> None:
    """Collect a location by hand via the Web UI form."""
    fields = [
        InputFieldDescription(
            name='city',
            label='City',
            type=InputFieldType.TEXT,
            description='The city the device is in',
            default_value=location.city if location else None,
        ),
        InputFieldDescription(
            name='country',
            label='Country',
            type=InputFieldType.TEXT,
            description='The country the device is in',
            default_value=location.country if location else None,
        ),
        InputFieldDescription(
            name='timezone',
            label='Time Zone',
            type=InputFieldType.TEXT,
            description='IANA time zone, e.g. Europe/Berlin',
            default_value=location.timezone if location else None,
            required=True,
        ),
        InputFieldDescription(
            name='latitude',
            label='Latitude',
            type=InputFieldType.NUMBER,
            description='Decimal degrees, e.g. 52.52',
            default_value=str(location.latitude) if location else None,
            required=True,
        ),
        InputFieldDescription(
            name='longitude',
            label='Longitude',
            type=InputFieldType.NUMBER,
            description='Decimal degrees, e.g. 13.405',
            default_value=str(location.longitude) if location else None,
            required=True,
        ),
    ]

    try:
        _, result = await ubo_input(
            prompt='Set the device location',
            descriptions=[WebUIInputDescription(fields=fields)],
        )
    except asyncio.CancelledError:
        logger.info('Localization: location form cancelled')
        return

    data = result.data if result else {}

    timezone = (data.get('timezone', '') or '').strip()
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        _notify(
            'Invalid Time Zone',
            f'"{timezone}" is not an IANA time zone. Try e.g. Europe/Berlin.',
        )
        return

    try:
        latitude = float(data.get('latitude', '') or '')
        longitude = float(data.get('longitude', '') or '')
    except ValueError:
        _notify(
            'Invalid Coordinates',
            'Latitude and longitude must be decimal numbers.',
        )
        return

    city = (data.get('city', '') or '').strip() or None
    country = (data.get('country', '') or '').strip() or None

    store.dispatch(
        LocalizationSetLocationAction(
            location=LocationInfo(
                latitude=latitude,
                longitude=longitude,
                city=city,
                country=country,
                # We can't infer the country code from a free-text country, and
                # it only drives °C vs °F — leave it unset rather than guess.
                country_code=None,
                timezone=timezone,
            ),
            source=LocationSource.MANUAL,
        ),
    )


@store.with_state(lambda state: state.localization.location)
def _open_location_form(location: LocationInfo | None) -> None:
    create_task(_location_form(location))


def _reset_location() -> None:
    store.dispatch(LocalizationResetLocationAction())


def register_location_actions() -> None:
    """Register the handlers the Location menu items dispatch."""
    register_action(
        SET_LOCATION_ACTION_ID,
        _open_location_form,
        allow_reregister=True,
    )
    register_action(
        RESET_LOCATION_ACTION_ID,
        _reset_location,
        allow_reregister=True,
    )


@store.autorun(
    lambda state: (state.localization.location, state.localization.location_source),
)
def build_location_menu(
    data: tuple[LocationInfo | None, LocationSource],
) -> None:
    """Rebuild the Location menu whenever the location or its origin changes."""
    location, source = data

    items: tuple[MenuItemData | None, ...] = (
        MenuItemData(
            key='set-manually',
            label='Set Manually',
            icon='󰏫',
            action_id=SET_LOCATION_ACTION_ID,
        ),
        MenuItemData(
            key='reset',
            label='Reset to Automatic',
            icon='󰑐',
            action_id=RESET_LOCATION_ACTION_ID,
        )
        if source is LocationSource.MANUAL or location is not None
        else None,
    )

    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=LOCATION_MENU_ID,
            title='󰍎Location',
            heading='Device Location',
            sub_heading=describe_location(location, source),
            items=items,
            placeholder='',
        ),
    )
