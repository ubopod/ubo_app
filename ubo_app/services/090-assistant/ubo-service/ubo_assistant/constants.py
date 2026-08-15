"""Project constants."""

import os
from pathlib import Path

import platformdirs

# ``source_id`` on ``AssistantReportAction`` / ``AssistantHandleReportEvent``
# identifying which pipeline produced a frame. Mirrors
# ``ubo_app.store.services.assistant.LIVE_PIPELINE_SOURCE_ID`` /
# ``REQUEST_PIPELINE_SOURCE_ID``; kept here as bare strings because the
# subprocess can't import the core store package, but the two definitions
# must stay in sync — a mismatch silently breaks chat routing.
LIVE_PIPELINE_SOURCE_ID = 'pipecat'
REQUEST_PIPELINE_SOURCE_ID = 'assistant_request'

# Push-to-talk (manual) turn completion: on button release / listen-toggle off,
# wait for the streaming STT to finalize the last words before flushing the turn
# to the LLM. Re-armed on each incoming transcript (quiet window), bounded by a
# hard max ≈ the input transport's 2s trailing-silence flush plus margin.
MANUAL_RELEASE_QUIET_WINDOW_SECONDS = 0.6
MANUAL_RELEASE_MAX_WAIT_SECONDS = 2.5

# Cap the size of each emitted ``AudioSample``. Pipecat can hand us ~0.5 s
# frames (~48 KB at 48 kHz/16-bit), which overflow the heap of
# memory-constrained clients (the ESP32 LVGL client has ~50 KB free): nanopb's
# decode ``realloc`` fails and TTS goes silent. ~8 KB (~85 ms at 48 kHz) decodes
# comfortably everywhere; fuller clients just reassemble more, smaller chunks.
#
# Shared, not per-transport: every path that emits TTS audio has to honour it.
# It lived in ``ubo_output_transport`` alone, so the ``grpc_collector`` path
# (screen-reader / one-shot requests) shipped whole ~48 KB frames and the
# satellite lost most of the utterance.
MAX_AUDIO_CHUNK_BYTES = 8192

IS_RPI = Path('/etc/rpi-issue').exists()
DATA_PATH = Path(
    os.environ.get(
        'UBO_DATA_PATH',
        platformdirs.user_data_path(appname='ubo', ensure_exists=True),
    ),
)

DEFAULT_SYSTEM_MESSAGE = """
You are a helpful assistant who converses with a user and answers questions.
Your goals are to be helpful and brief in your responses.
Respond with one or two sentences at most, unless you are asked to
respond at more length.
Your output will be converted to audio so don't include special characters
in your answers.
"""

DEFAULT_TOOLS_MESSAGE = """
You have access to several tools.

Use "draw_image" to respond to requests about generating images.

Use "get_image" to answer questions about the user's video stream.
Some examples of phrases that indicate you should use the "get_image" tool are:
- What do you see?
- What's in the video?
- Can you describe the video?
- Tell me about what you see.
- Tell me something interesting about what you see.
- What's happening in the video?

Use "get_current_time" for any question about the time, the date, or the day of
the week. You have no clock of your own, so never guess these — always call the
tool, even if you were told the time earlier in the conversation.

Use "get_weather" for any question about the current weather or temperature.
Never guess the weather; always call the tool.

Use "set_location" when the user tells you where they are, for example "I live in
Lisbon" or "I'm in Berlin now". Supply the latitude, longitude, ISO country code
and IANA timezone you already know for that city rather than asking the user for
them. If "get_current_time" or "get_weather" reports that the device's location
is unknown, ask the user which city they are in and then call "set_location".

Use "run_device_command" to run one of the user's configured voice shortcuts when
they ask for something a shortcut covers.

You are not limited to these tools, you can answer general questions of the user and
engage in a conversation with them.
"""
