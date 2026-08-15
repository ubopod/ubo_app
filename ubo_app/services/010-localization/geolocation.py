"""Resolve the device's location from its public IP address.

GeoJS needs no API key and returns city, country, coordinates, the IANA
timezone and the caller's public IP in a single request. That last field is
what lets us detect a changed public IP without polling anything else: the
lookup *is* the check.
"""

from __future__ import annotations

from typing import NamedTuple

import aiohttp
from constants import GEOJS_URL, HTTP_TIMEOUT_SECONDS, USER_AGENT

from ubo_app.logger import logger
from ubo_app.store.services.localization import LocationInfo, LocationSource


class GeolocationResult(NamedTuple):
    """A successful IP-geolocation lookup."""

    location: LocationInfo
    public_ip: str | None


def _optional_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def parse_geolocation(payload: object) -> GeolocationResult | None:
    """Turn a GeoJS response into a ``GeolocationResult``, or ``None`` if unusable.

    Coordinates are the only fields we cannot do without — everything else is
    cosmetic or degradable.
    """
    if not isinstance(payload, dict):
        return None
    try:
        latitude = float(payload['latitude'])  # pyright: ignore [reportArgumentType]
        longitude = float(payload['longitude'])  # pyright: ignore [reportArgumentType]
    except (KeyError, TypeError, ValueError):
        return None

    return GeolocationResult(
        location=LocationInfo(
            latitude=latitude,
            longitude=longitude,
            city=_optional_str(payload, 'city'),
            country=_optional_str(payload, 'country'),
            country_code=_optional_str(payload, 'country_code'),
            timezone=_optional_str(payload, 'timezone'),
        ),
        public_ip=_optional_str(payload, 'ip'),
    )


async def fetch_geolocation() -> GeolocationResult | None:
    """Look the device's location up by its public IP. ``None`` on any failure."""
    try:
        async with (
            aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS),
            ) as session,
            session.get(
                GEOJS_URL,
                headers={'User-Agent': USER_AGENT},
                raise_for_status=True,
            ) as response,
        ):
            payload = await response.json(content_type=None)
    except Exception:
        logger.exception('Localization: IP geolocation lookup failed')
        return None

    result = parse_geolocation(payload)
    if result is None:
        logger.warning(
            'Localization: unusable IP geolocation response',
            extra={'payload': payload},
        )
    return result


def should_apply_geolocation(
    result: GeolocationResult,
    *,
    current_public_ip: str | None,
    location_source: LocationSource,
    has_location: bool,
) -> bool:
    """Decide whether a fresh lookup should overwrite what we already have.

    A manually set location is authoritative. Otherwise, an unchanged public IP
    means an unchanged location, so we leave state alone (and avoid the churn of
    a needless re-render and weather refetch).
    """
    if location_source is LocationSource.MANUAL:
        return False
    return not (
        has_location
        and result.public_ip is not None
        and result.public_ip == current_public_ip
    )
