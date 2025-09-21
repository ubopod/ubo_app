"""TTS service that wraps multiple TTS services allowing switching between them."""

from collections.abc import AsyncGenerator

from loguru import logger
from pipecat.frames.frames import Frame
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.tts import GoogleTTSService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.services.rime.tts import RimeTTSService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from ubo_bindings.client import UboRPCClient

from ubo_assistant.piper import PiperTTSService
from ubo_assistant.switch import UboSwitchService


class UboTTSService(UboSwitchService[TTSService], TTSService):
    """TTS service that wraps multiple TTS services allowing switching between them."""

    def __init__(
        self,
        client: UboRPCClient,
        *,
        google_credentials: str | None,
        openai_api_key: str | None,
        elevenlabs_api_key: str | None,
        elevenlabs_voice_id: str | None,
        rime_api_key: str | None,
        selector: str,
    ) -> None:
        """Initialize TTS service with Google, OpenAI, ElevenLabs, and Piper."""
        try:
            if google_credentials:
                self.google_tts = GoogleTTSService(credentials=google_credentials)
            else:
                self.google_tts = None
        except Exception:
            logger.exception('Error while initializing Google TTS')
            self.google_tts = None

        try:
            if openai_api_key:
                self.openai_tts = OpenAITTSService(api_key=openai_api_key)
            else:
                self.openai_tts = None
        except Exception:
            logger.exception('Error while initializing OpenAI TTS')
            self.openai_tts = None

        try:
            if elevenlabs_api_key and elevenlabs_voice_id:
                self.elevenlabs_tts = ElevenLabsTTSService(
                    api_key=elevenlabs_api_key,
                    voice_id=elevenlabs_voice_id,
                    sample_rate=24000,
                    model='eleven_turbo_v2_5',
                )
                logger.info('ElevenLabs TTS initialized successfully')
            else:
                self.elevenlabs_tts = None
                logger.info('ElevenLabs TTS not initialized')
        except Exception:
            logger.exception('Error while initializing ElevenLabs TTS')
            self.elevenlabs_tts = None

        try:
            self.piper_tts = PiperTTSService()
        except Exception:
            logger.exception('Error while initializing Piper TTS')
            self.piper_tts = None

        try:
            if rime_api_key:
                self.rime_tts = RimeTTSService(
                    api_key=rime_api_key,
                    voice_id='antoine',
                    model='mistv2',
                    params=RimeTTSService.InputParams(
                        language=Language.EN,
                        speed_alpha=1.0,
                        reduce_latency=False,
                        pause_between_brackets=True,
                        phonemize_between_brackets=False,
                    ),
                )
                logger.info('Rime TTS initialized successfully')
            else:
                self.rime_tts = None
                logger.info('Rime TTS not initialized')
        except Exception:
            logger.exception('Error while initializing Rime TTS')
            self.rime_tts = None

        self._services = {
            'google': self.google_tts,
            'openai': self.openai_tts,
            'elevenlabs': self.elevenlabs_tts,
            'piper': self.piper_tts,
            'rime': self.rime_tts,
        }

        UboSwitchService.__init__(self, client=client, selector=selector)
        TTSService.__init__(self)

    async def run_tts(self, text: str) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Run TTS on the given text and yield frames."""
        _ = text
        yield None
