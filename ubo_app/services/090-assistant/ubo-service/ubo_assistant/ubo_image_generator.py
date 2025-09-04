"""Image generator service that wraps multiple image generation services."""

from collections.abc import AsyncGenerator

import aiohttp
from loguru import logger
from pipecat.frames.frames import Frame
from pipecat.services.google.image import GoogleImageGenService
from pipecat.services.image_service import ImageGenService
from pipecat.services.openai.image import OpenAIImageGenService
from ubo_bindings.client import UboRPCClient

from ubo_assistant.switch import UboSwitchService


class UboImageGeneratorService(UboSwitchService[ImageGenService], ImageGenService):
    """Image generator service that wraps multiple image generator services."""

    def __init__(
        self,
        client: UboRPCClient,
        *,
        google_api_key: str | None,
        openai_api_key: str | None,
        selector: str,
    ) -> None:
        """Initialize the STT service with Google, OpenAI, and Vosk STT services."""
        self._assistance_index = 0
        try:
            if google_api_key:
                self.google_image_generator = GoogleImageGenService(
                    api_key=google_api_key,
                )
            else:
                self.google_image_generator = None
        except Exception:
            logger.exception('Error while initializing Google image generator')
            self.google_image_generator = None

        try:
            self.aiohttp_session = aiohttp.ClientSession()
            if openai_api_key:
                self.openai_image_generator = OpenAIImageGenService(
                    api_key=openai_api_key,
                    image_size='1024x1024',
                    aiohttp_session=self.aiohttp_session,
                )
            else:
                self.openai_image_generator = None
        except Exception:
            logger.exception('Error while initializing OpenAI image generator')
            self.openai_image_generator = None

        self._services = {
            'google': self.google_image_generator,
            'openai': self.openai_image_generator,
        }

        UboSwitchService.__init__(self, client=client, selector=selector)
        ImageGenService.__init__(self)

    async def run_image_gen(self, prompt: str) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Ignore this as child classes will handle audio processing."""
        _ = prompt
        yield None
