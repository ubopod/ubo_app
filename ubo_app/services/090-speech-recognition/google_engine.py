"""Google Stack Assistant with Gemini API and Speech Recognition."""

import asyncio
import json
import re
import time
from collections.abc import Generator

from abstraction import NeedsSetupMixin, SpeechRecognitionMixin
from google.cloud import speech_v2 as speech
from google.oauth2 import service_account

from ubo_app.constants import (
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_PATTERN,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
    SPEECH_RECOGNITION_FRAME_RATE,
)
from ubo_app.store.input.types import InputFieldDescription, InputFieldType
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionEngineName,
    SpeechRecognitionSetSelectedEngineAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import ToThreadOptions, create_task, to_thread
from ubo_app.utils.input import ubo_input


class GoogleEngine(NeedsSetupMixin, SpeechRecognitionMixin):
    """Google speech recognition engine using Google Cloud Speech-to-Text."""

    _task: asyncio.Task[None] | None = None

    def __init__(self) -> None:
        """Initialize the Google speech recognition engine."""
        super().__init__(
            name=SpeechRecognitionEngineName.GOOGLE,
            label='Google Cloud',
            not_setup_message='Google Cloud service account key is not set. You can '
            'set it in the settings.',
        )

    def _requests_stream(
        self,
    ) -> Generator[speech.StreamingRecognizeRequest, None, None]:
        """Generate audio stream for transcription."""
        yield self._config_request
        while self.ongoing_recognition:
            try:
                sample = self.input_chunks_queue.get_nowait()
            except IndexError:
                time.sleep(0.05)
                continue
            else:
                yield speech.StreamingRecognizeRequest(audio=sample)

    def _run_loop(self) -> None:
        service_account_info_string = secrets.read_secret(
            GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
        )
        assert service_account_info_string  # noqa: S101
        service_account_info = json.loads(service_account_info_string)
        streaming_config = speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                explicit_decoding_config=speech.ExplicitDecodingConfig(
                    sample_rate_hertz=SPEECH_RECOGNITION_FRAME_RATE,
                    audio_channel_count=1,
                    encoding=speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                ),
                language_codes=['en-US'],
                model='long',
            ),
        )
        self._config_request = speech.StreamingRecognizeRequest(
            recognizer=f'projects/{service_account_info["project_id"]}/locations/global/recognizers/_',
            streaming_config=streaming_config,
        )

        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
        )
        client = speech.SpeechClient(credentials=credentials)
        responses = client.streaming_recognize(requests=self._requests_stream())

        for response in responses:
            for result in response.results:
                if result.is_final and result.alternatives:
                    create_task(self.report(result=result.alternatives[0].transcript))
                    break

    async def _run(self) -> None:
        """Run the Google speech recognition engine."""
        to_thread(
            self._run_loop,
            ToThreadOptions(callback=self._set_task, name='VoskEngine.run'),
        )

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

    def setup(self) -> None:
        """Set up the Google speech recognition engine."""

        async def act() -> None:
            _, result = await ubo_input(
                title='Google Cloud Service Account Key',
                prompt='Enter your service account key, it should have at least '
                '"Google Speech Client" role.',
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
            )
            secrets.write_secret(
                key=GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
                value=result.files['service_account_key'].decode('utf-8'),
            )
            store.dispatch(
                SpeechRecognitionSetSelectedEngineAction(
                    engine_name=SpeechRecognitionEngineName.GOOGLE,
                ),
            )

        create_task(act())
