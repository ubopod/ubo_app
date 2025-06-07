"""Google Cloud LLM Assistant Engine Implementation."""

import asyncio
import json
from collections.abc import AsyncIterable

from abstraction.text_processing_assistant_mixin import TextProcessingAssistantMixin
from typing_extensions import override

from ubo_app.constants import GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID
from ubo_app.engines.google_cloud import GoogleEngine
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantEngineName,
    AssistantSetSelectedEngineAction,
)
from ubo_app.utils import secrets


class GoogleAssistantEngine(GoogleEngine, TextProcessingAssistantMixin):
    """Google speech recognition engine using Google Cloud Speech-to-Text."""

    _task: asyncio.Task[None] | None = None

    def __init__(self) -> None:
        """Initialize the Google speech recognition engine."""
        self.engine_name = AssistantEngineName.GOOGLE
        super().__init__(name=self.engine_name)

    async def _run(self) -> None:
        import vertexai
        from google.oauth2 import service_account
        from vertexai.generative_models import (
            Content,
            GenerationResponse,
            GenerativeModel,
            Part,
        )

        service_account_info_string = secrets.read_secret(
            GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID,
        )
        assert service_account_info_string  # noqa: S101
        service_account_info = json.loads(service_account_info_string)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
        )
        vertexai.init(
            project=service_account_info['project_id'],
            credentials=credentials,
        )

        @store.with_state(
            lambda state: state.assistant.selected_models[AssistantEngineName.GOOGLE],
        )
        async def process_text(
            model_name: str,
            text: str,
        ) -> AsyncIterable[GenerationResponse]:
            model = GenerativeModel(model_name)

            return await model.generate_content_async(
                contents=[
                    Content(
                        role='model',
                        parts=[
                            Part.from_text('Please write short and concise answers.'),
                            Part.from_text("""it is going to be read by a simple text \
to speech engine. So please answer only with English letters, numbers and standard \
production like period, comma, colon, single and double quotes, exclamation mark, \
question mark, and dash. Do not use any other special characters or emojis."""),
                        ],
                    ),
                    Content(
                        role='user',
                        parts=[Part.from_text(text)],
                    ),
                ],
                stream=True,
            )

        while True:
            text = await self.input_queue.get()
            try:
                async for chunk in await process_text(text):
                    chunk_text: str = chunk.text
                    await self.report(chunk_text)
            finally:
                await self._complete_assistance()

    @override
    async def _setup_google_cloud_service_account_key(self) -> None:
        await super()._setup_google_cloud_service_account_key()
        store.dispatch(
            AssistantSetSelectedEngineAction(engine_name=self.engine_name),
        )
