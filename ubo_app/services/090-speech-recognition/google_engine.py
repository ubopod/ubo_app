"""Google Cloud Speech Recognition Engine Implementation."""

import asyncio
import json
import re
import time
from collections.abc import Generator

from abstraction.speech_recognition_mixin import SpeechRecognitionMixin
from typing_extensions import override

from ubo_app.constants import (
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_PATTERN,
    GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
    SPEECH_RECOGNITION_FRAME_RATE,
)
from ubo_app.engines.google_cloud import GoogleEngine
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionEngineName,
    SpeechRecognitionSetSelectedEngineAction,
)
from ubo_app.utils import secrets
from ubo_app.utils.async_ import ToThreadOptions, create_task, to_thread


class GoogleSpeechRecognitionEngine(GoogleEngine, SpeechRecognitionMixin):
    """Google speech recognition engine using Google Cloud Speech-to-Text."""

    _task: asyncio.Task[None] | None = None

    def __init__(self) -> None:
        """Initialize the Google speech recognition engine."""
        self.engine_name = SpeechRecognitionEngineName.GOOGLE
        super().__init__(name=self.engine_name)

    def _run_loop(self) -> None:
        from google.cloud import speech_v2 as speech
        from google.oauth2 import service_account

        def requests_stream() -> Generator[
            speech.StreamingRecognizeRequest,
            None,
            None,
        ]:
            """Generate audio stream for transcription."""
            yield self._config_request
            while self.should_be_running():
                try:
                    sample = self.input_queue.get_nowait()
                except IndexError:
                    time.sleep(0.05)
                    continue
                else:
                    yield speech.StreamingRecognizeRequest(audio=sample)

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
        responses = client.streaming_recognize(requests=requests_stream())

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

    @override
    async def _setup_google_cloud_service_account_key(self) -> None:
        await super()._setup_google_cloud_service_account_key()
        store.dispatch(
            SpeechRecognitionSetSelectedEngineAction(
                engine_name=self.engine_name,
            ),
        )
