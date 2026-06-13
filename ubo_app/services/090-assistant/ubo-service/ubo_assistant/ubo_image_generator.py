"""Image generator service that wraps multiple image generation services."""

import base64
import io
from collections.abc import AsyncGenerator
from typing import cast

import aiohttp
from loguru import logger
from PIL import Image
from pipecat.frames.frames import ErrorFrame, Frame, URLImageRawFrame
from pipecat.services.google.image import GoogleImageGenService
from pipecat.services.image_service import ImageGenService
from pipecat.services.openai.image import OpenAIImageGenService, OpenAIImageSize
from pipecat.services.settings import ImageGenSettings, assert_given
from ubo_bindings.client import UboRPCClient

from ubo_assistant.switch import UboSwitchService


class UboOpenAIImageGenService(OpenAIImageGenService):
    """OpenAI image generator that also supports ``gpt-image-1``.

    Pipecat's :meth:`OpenAIImageGenService.run_image_gen` reads
    ``image.data[0].url``, but ``gpt-image-1`` only ever returns base64
    (``b64_json``) and never a URL, so the stock implementation fails with
    "Image generation failed". This override decodes whichever representation
    the provider returns, so it works for both ``gpt-image-1`` and the
    ``dall-e-*`` models.
    """

    async def run_image_gen(self, prompt: str) -> AsyncGenerator[Frame, None]:
        """Generate an image, handling both base64 and URL responses."""
        logger.debug('Generating image from prompt: {prompt}', prompt=prompt)

        size = cast(
            'OpenAIImageSize | None',
            assert_given(self._settings.image_size),
        )
        response = await self._client.images.generate(
            prompt=prompt,
            model=assert_given(self._settings.model),
            n=1,
            size=size,
        )

        if not response.data:
            yield ErrorFrame('Image generation failed: no data returned')
            return

        datum = response.data[0]
        if datum.b64_json:
            image_bytes = base64.b64decode(datum.b64_json)
        elif datum.url:
            async with self._aiohttp_session.get(datum.url) as http_response:
                image_bytes = await http_response.content.read()
        else:
            yield ErrorFrame('Image generation failed')
            return

        image = Image.open(io.BytesIO(image_bytes))
        yield URLImageRawFrame(
            image=image.tobytes(),
            size=image.size,
            format=image.format,
            url=datum.url or '',
        )


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
                self.openai_image_generator = UboOpenAIImageGenService(
                    api_key=openai_api_key,
                    model='gpt-image-1',
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

        UboSwitchService.__init__(
            self,
            client=client,
            selector=selector,
            settings=ImageGenSettings(model=None),
        )

    async def run_image_gen(self, prompt: str) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Ignore this as child classes will handle audio processing."""
        _ = prompt
        yield None
