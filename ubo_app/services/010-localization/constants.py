"""Constants for the localization service's location and weather features.

Both upstream services are deliberately key-less: the device must be able to
answer "what time is it" and "what's the weather" out of the box, without the
user signing up anywhere. GeoJS resolves the public IP to a coarse location
(and, crucially, an IANA timezone); MET Norway serves the forecast.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

GEOJS_URL = 'https://get.geojs.io/v1/ip/geo.json'
MET_NO_URL = 'https://api.met.no/weatherapi/locationforecast/2.0/compact'


def _user_agent() -> str:
    """Build the identifying User-Agent MET Norway's terms of service require."""
    try:
        package_version = version('ubo-app')
    except PackageNotFoundError:
        package_version = 'dev'
    return f'ubo-app/{package_version} github.com/ubopod/ubo-app accounts@getubo.com'


USER_AGENT = _user_agent()

HTTP_TIMEOUT_SECONDS = 10

# Connectivity flaps while Wi-Fi associates and captive portals briefly look
# "connected", so let the link settle before spending a lookup on it.
GEO_DEBOUNCE_SECONDS = 10
GEO_BACKOFF_SCHEDULE = (10, 30, 60, 120, 300)

# MET Norway asks clients not to re-request before the forecast expires; when
# the response carries no `Expires` header we fall back to this.
WEATHER_FALLBACK_TTL_SECONDS = 30 * 60

# How often the background refresher wakes to see whether the cached forecast
# has expired. It is only the tick — `expires_at` is the actual gate, because
# MET Norway's terms require honouring their `Expires` header rather than
# polling on a schedule of our own. Weather does not change fast enough for a
# finer tick to buy anything.
WEATHER_REFRESH_CHECK_SECONDS = 10 * 60
