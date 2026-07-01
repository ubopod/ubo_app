"""Pure WiFi input-form schemas and result parsing.

Hardware-free on purpose: this module must NOT import ``wifi_manager`` (and
therefore ``sdbus``), so the form-description and parsing logic can be unit
tested without D-Bus present.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from str_to_bool import str_to_bool

from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    QRCodeInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.store.services.wifi import WiFiType

if TYPE_CHECKING:
    from collections.abc import Sequence

    from wifi_manager import WiFiNetwork

    from ubo_app.store.input.types import InputResult

# Regular expression pattern
# WIFI:S:<SSID>;T:<WEP|WPA|blank>;P:<PASSWORD>;H:<true|false|blank>;;
BARCODE_PATTERN = (
    r'^WIFI:S:(?P<SSID>[^;]*);(?:T:(?P<Type>(?i:WEP|WPA|WPA2|nopass));)'
    r'?(?:P:(?P<Password>[^;]*);)?(?:H:(?P<Hidden>(?i:true|false));)?;?$|'
    r'^WIFI:T:(?P<Type_>(?i:WEP|WPA|WPA2|nopass));S:(?P<SSID_>[^;]*);'
    r'(?:P:(?P<Password_>[^;]*);)?(?:H:(?P<Hidden_>(?i:true|false|));)?;?$'
)

# Distinct option value for "enter the network manually". The ellipsis makes a
# collision with a real SSID unlikely.
OTHER_OPTION = 'Other network…'


def qr_description() -> QRCodeInputDescription:
    """Camera/QR-code WiFi input."""
    return QRCodeInputDescription(
        id='wifi:qr-input',
        pattern=BARCODE_PATTERN,
        instructions=ReadableInformation(
            text='Go to your phone settings, choose QR code and hold it in '
            'front of the camera to scan it.',
            picovoice_text='Go to your phone settings, choose {QR|K Y UW AA R} '
            'code and hold it in front of the camera to scan it.',
        ),
    )


def full_webui_description() -> WebUIInputDescription:
    """Full manual web form: SSID, password, security type, hidden flag."""
    return WebUIInputDescription(
        id='wifi:web-ui-input',
        fields=[
            InputFieldDescription(
                name='SSID',
                label='SSID',
                type=InputFieldType.TEXT,
                description='The name of the WiFi network',
                required=True,
            ),
            InputFieldDescription(
                name='Password',
                label='Password',
                type=InputFieldType.PASSWORD,
                description='The password of the WiFi network',
                required=False,
            ),
            InputFieldDescription(
                name='Type',
                label='Type',
                type=InputFieldType.SELECT,
                description='The type of the WiFi network',
                default_value='WPA2',
                options=['WEP', 'WPA', 'WPA2', 'nopass'],
                required=False,
            ),
            InputFieldDescription(
                name='Hidden',
                label='Hidden',
                type=InputFieldType.CHECKBOX,
                description='Is the WiFi network hidden?',
                default_value='false',
                required=False,
            ),
        ],
    )


def password_only_description() -> WebUIInputDescription:
    """Password-only web form (SSID + security already known from the scan)."""
    return WebUIInputDescription(
        id='wifi:web-ui-input',
        fields=[
            InputFieldDescription(
                name='Password',
                label='Password',
                type=InputFieldType.PASSWORD,
                description='The password of the WiFi network',
                required=False,
            ),
        ],
    )


def network_select_description(
    networks: Sequence[WiFiNetwork],
) -> WebUIInputDescription:
    """Step-1 web form: pick a scanned network or 'Other'."""
    return WebUIInputDescription(
        id='wifi:web-ui-input',
        fields=[
            InputFieldDescription(
                name='Network',
                label='Network',
                type=InputFieldType.SELECT,
                description='Choose your WiFi network',
                options=[network.ssid for network in networks] + [OTHER_OPTION],
                required=True,
            ),
        ],
    )


def parse_full_result(
    result: InputResult,
) -> tuple[str | None, str | None, WiFiType | None, bool]:
    """Extract (ssid, password, type, hidden) from a QR/full-form result.

    ``type`` is returned as a real ``WiFiType`` enum (not a bare string) so
    open-network handling can compare it by equality without surprises.
    """
    ssid = result.data.get('SSID') or result.data.get('SSID_')
    password = result.data.get('Password') or result.data.get('Password_')
    type_value = result.data.get('Type') or result.data.get('Type_')
    type = WiFiType(type_value.upper()) if type_value else None
    hidden = str_to_bool(
        result.data.get('Hidden') or result.data.get('Hidden_') or 'false',
    )
    return ssid, password, type, hidden
