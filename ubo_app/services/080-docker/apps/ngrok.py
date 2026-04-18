"""Ngrok tunnel Docker app."""

from __future__ import annotations

from apps._registry import ContainerEntry
from ubo_app.store.input.types import (
    QRCodeInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.services.speech_synthesis import ReadableInformation
from ubo_app.utils.input import ubo_input

ENTRY = ContainerEntry(
    id='ngrok',
    label='Ngrok',
    icon='󰛶',
    network_mode='host',
    path='ngrok/ngrok:latest',
    registry='docker.io',
    environment_vairables={
        'NGROK_AUTHTOKEN': lambda: ubo_input(
            resolver=lambda code, _: code,
            prompt='Enter the Ngrok Auth Token',
            descriptions=[
                QRCodeInputDescription(
                    instructions=ReadableInformation(
                        text="""\
Follow these steps:

1. Login to your ngrok account.
2. Get the authentication token from the dashboard.
3. Convert it to QR code.
4. Scan QR code to input the token.""",
                        picovoice_text="""\
Follow these steps:

1. Login to your {ngrok|EH N G EH R AA K} account
2. Get the authentication token from the dashboard
3. Convert it to {QR|K Y UW AA R} code
4. Scan QR code to input the token""",
                    ),
                    pattern=rf'^[a-zA-Z0-9]{20, 30}_[a-zA-Z0-9]{20, 30}$',
                ),
                WebUIInputDescription(),
            ],
        ),
    },
    command=lambda: ubo_input(
        resolver=lambda code, _: code,
        prompt='Enter the command, for example: `http 80` or `tcp 22`',
        descriptions=[
            QRCodeInputDescription(
                instructions=ReadableInformation(
                    text='This is the command you would enter when running '
                    'ngrok. Refer to ngrok documentation for further '
                    'information',
                    picovoice_text="""\
This is the command you would enter when running {ngrok|EH N G EH R AA K}.
Refer to {ngrok|EH N G EH R AA K} documentation for further information""",
                ),
            ),
            WebUIInputDescription(),
        ],
    ),
)
