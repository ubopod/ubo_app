"""Input frame for image generation services."""

from dataclasses import dataclass

from pipecat.frames.frames import TextFrame


@dataclass
class ImageGenFrame(TextFrame):
    """Frame to be consumed by image generation services."""
