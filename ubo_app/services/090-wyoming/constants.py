"""Constants for the Home Assistant Wyoming integration."""

from __future__ import annotations

import os

MAX_TCP_PORT = 65_535


def _port_from_environment(name: str, default: int) -> int:
    """Read a valid TCP port without making startup depend on malformed config."""
    try:
        port = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return port if 1 <= port <= MAX_TCP_PORT else default


WYOMING_SATELLITE_LISTEN_PORT = _port_from_environment(
    'UBO_WYOMING_SATELLITE_LISTEN_PORT',
    10700,
)
WYOMING_ENGINES_LISTEN_PORT = _port_from_environment(
    'UBO_WYOMING_ENGINES_LISTEN_PORT',
    10600,
)

PCM_WIDTH_BYTES = 2
MAX_AUDIO_CHANNELS = 2
MIN_AUDIO_RATE = 8_000
MAX_AUDIO_RATE = 96_000
SATELLITE_MIC_QUEUE_SIZE = 40
MAX_ASR_AUDIO_BYTES = 10 * 1024 * 1024
MAX_TTS_AUDIO_BYTES = 20 * 1024 * 1024
MAX_ENGINE_REQUESTS = 2
ASSISTANT_REQUEST_TIMEOUT_SECONDS = 60.0
PLAYBACK_DONE_TIMEOUT_SECONDS = 90.0
# Upper bound on how long one wake-triggered utterance streams to Home Assistant.
# Home Assistant normally ends it far sooner (``voice-stopped`` from its VAD, or
# ``transcript`` when speech-to-text completes); this only bounds the microphone
# when neither arrives — e.g. a speech-to-text provider that does its own
# endpointing and then stalls.
MAX_UTTERANCE_SECONDS = 30.0

UBO_NET_NAME = 'ubo_net'

WYOMING_MENU_ID = 'wyoming:main'
STATUS_ICON_ID = 'wyoming:state'
SECURITY_WARNING_ID = 'wyoming:network-warning'
