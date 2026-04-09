"""Google Cloud engine interface."""

import re

from typing_extensions import override

from ubo_app.constants.assistant import (
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_PATTERN,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
)
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.abstraction.remote_mixin import RemoteMixin
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    PathInputDescription,
    WebUIInputDescription,
)
from ubo_app.store.services.file_system import PathSelectorConfig
from ubo_app.utils import secrets
from ubo_app.utils.input import ubo_input


class GoogleCloudEngine(NeedsSetupMixin, AIProviderMixin, RemoteMixin):
    """Google Cloud engine."""

    @property
    def name(self) -> str:
        """The name of the Google Cloud engine."""
        return 'google_cloud'

    @property
    def label(self) -> str:
        """The label of the Google Cloud engine."""
        return 'Google Cloud'

    @property
    def not_setup_message(self) -> str:
        """The message to display when the Google Cloud engine is not set up."""
        return (
            'Google Cloud service account key is not set. You can '
            'set it in the settings.'
        )

    @property
    @override
    def is_setup(self) -> bool:
        """Check if the Google Cloud engine is set up."""
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

    async def _setup(self) -> None:
        _, result = await ubo_input(
            title='Google Cloud Service Account Key',
            prompt='Enter your service account key, it should have at least '
            '"Google Speech Client" role or "Vertex AI User" role.',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='service_account_key',
                            type=InputFieldType.FILE,
                            label='Service Account Key',
                            description='JSON key file for Google Cloud Service '
                            'Account',
                            file_mimetype='application/json',
                            required=True,
                            pattern=GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_PATTERN,
                        ),
                    ],
                ),
                PathInputDescription(
                    title='Google Cloud Service Account Key',
                    prompt='Select the JSON key file for Google Cloud Service Account.',
                    selector_config=PathSelectorConfig(
                        show_hidden=True,
                        accepts_files=True,
                        acceptable_suffixes=('.json',),
                    ),
                ),
            ],
        )
        upload_id = result.data.get('service_account_key_upload_id')
        if upload_id:
            from ubo_app.utils.file_upload import (
                await_completed_upload,
            )

            file_content = await await_completed_upload(upload_id)
        else:
            file_content = result.files['service_account_key']
        secrets.write_secret(
            key=GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
            value=file_content.decode('utf-8'),
        )
