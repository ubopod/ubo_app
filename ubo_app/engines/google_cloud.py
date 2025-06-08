"""Google Cloud engine implementation."""

import asyncio
import re

from typing_extensions import override

from ubo_app.constants import (
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_PATTERN,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
)
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input


class GoogleEngine(NeedsSetupMixin):
    """Google speech recognition engine using Google Cloud Speech-to-Text."""

    _task: asyncio.Task[None] | None = None

    def __init__(self, name: str) -> None:
        """Initialize the Google speech recognition engine."""
        super().__init__(
            name=name,
            label='Google Cloud',
            not_setup_message='Google Cloud service account key is not set. You can '
            'set it in the settings.',
        )

    @override
    def is_setup(self) -> bool:
        """Check if the Google speech recognition engine is set up."""
        service_account_info_string = secrets.read_secret(
            GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
        )
        return (
            bool(service_account_info_string)
            and re.match(
                GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_PATTERN,
                service_account_info_string,
            )
            is not None
        )

    async def _setup_google_cloud_service_account_key(self) -> None:
        _, result = await ubo_input(
            title='Google Cloud Service Account Key',
            prompt='Enter your service account key, it should have at least '
            '"Google Speech Client" role.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='service_account_key',
                            type=InputFieldType.FILE,
                            label='Service Account Key',
                            description='JSON key file for Google Cloud Speech-to-Text',
                            file_mimetype='application/json',
                            required=True,
                            pattern=GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_PATTERN,
                        ),
                    ],
                ),
            ],
        )
        secrets.write_secret(
            key=GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
            value=result.files['service_account_key'].decode('utf-8'),
        )

    @override
    def setup(self) -> None:
        """Set up the Google speech recognition engine."""
        create_task(self._setup_google_cloud_service_account_key())
