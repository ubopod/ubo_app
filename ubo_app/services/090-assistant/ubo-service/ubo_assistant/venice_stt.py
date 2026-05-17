"""Venice AI STT service — thin subclass of OpenAISTTService.

Venice's beta /audio/transcriptions endpoint rejects ``response_format=verbose_json``
(only ``json`` and ``text`` are accepted) and does not support the ``include=logprobs``
parameter. Pipecat's ``OpenAISTTService._transcribe`` requests ``verbose_json`` whenever
``_include_prob_metrics`` is on for non-OpenAI models, which would 400 against Venice.
This override pins ``response_format="json"`` and never requests logprobs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pipecat.services.openai.stt import OpenAISTTService

if TYPE_CHECKING:
    from openai.types.audio import Transcription


class VeniceSTTService(OpenAISTTService):
    """OpenAI-compatible STT against Venice with response_format pinned to json."""

    async def _transcribe(self, audio: bytes) -> Transcription:
        kwargs: dict[str, Any] = {
            'file': ('audio.wav', audio, 'audio/wav'),
            'model': self._settings.model,
            'response_format': 'json',
        }

        if self._settings.language is not None:
            kwargs['language'] = self._settings.language

        if self._settings.prompt is not None:
            kwargs['prompt'] = self._settings.prompt

        if self._settings.temperature is not None:
            kwargs['temperature'] = self._settings.temperature

        return await self._client.audio.transcriptions.create(**kwargs)
