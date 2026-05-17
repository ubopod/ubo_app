"""Venice AI TTS service — thin subclass of OpenAITTSService.

Pipecat's ``OpenAITTSService.run_tts`` resolves the voice through a hardcoded
``VALID_VOICES`` dict that only knows OpenAI's voice IDs (``alloy``, ``echo``...).
Venice exposes a different catalog (``af_sky``, ``af_bella``, ``eve``, ``rex``,
etc.) per TTS model family, so the lookup raises ``KeyError`` for any Venice
voice. This override passes the voice through verbatim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from openai import BadRequestError
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.utils.tracing.service_decorators import traced_tts

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from pipecat.frames.frames import Frame


class VeniceTTSService(OpenAITTSService):
    """OpenAI-compatible TTS against Venice with voice passed through verbatim."""

    @traced_tts
    async def run_tts(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        text: str,
        context_id: str,
    ) -> AsyncGenerator[Frame, None]:
        """Generate speech via Venice; voice is sent as-is (no OpenAI voice map)."""
        logger.debug('{self}: Generating TTS [{text}]', self=self, text=text)
        try:
            create_params = {
                'input': text,
                'model': self._settings.model,
                'voice': self._settings.voice,
                'response_format': 'pcm',
            }

            if self._settings.instructions:
                create_params['instructions'] = self._settings.instructions

            if self._settings.speed:
                create_params['speed'] = self._settings.speed

            async with self._client.audio.speech.with_streaming_response.create(
                **create_params,
            ) as r:
                if r.status_code != 200:  # noqa: PLR2004
                    error = await r.text()
                    logger.error(
                        '{self} error getting audio (status: {status}, error: {error})',
                        self=self,
                        status=r.status_code,
                        error=error,
                    )
                    yield ErrorFrame(
                        error=(
                            f'Error getting audio (status: {r.status_code}, '
                            f'error: {error})'
                        ),
                    )
                    return

                await self.start_tts_usage_metrics(text)

                chunk_size = self.chunk_size

                async for chunk in r.iter_bytes(chunk_size):
                    if len(chunk) > 0:
                        await self.stop_ttfb_metrics()
                        yield TTSAudioRawFrame(
                            chunk,
                            self.sample_rate,
                            1,
                            context_id=context_id,
                        )
        except BadRequestError as e:
            yield ErrorFrame(error=f'Unknown error occurred: {e}')
