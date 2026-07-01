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
You have access to two tools: "draw_image" and "get_image".
You can respond to requests about generating images by using the "draw_image" tool.
You can answer questions about the user's video stream using the get_image tool.
Some examples of phrases that indicate you should use the "get_image" tool are:
- What do you see?
- What's in the video?
- Can you describe the video?
- Tell me about what you see.
- Tell me something interesting about what you see.
- What's happening in the video?
You are not limited to these tools, you can answer general questions of the user and
engage in a conversation with them.
"""
