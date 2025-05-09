"""Constants for the Piper speech synthesis engine."""

from ubo_app.constants import CACHE_PATH

PIPER_MODEL = 'en/en_US/kristin/medium/en_US-kristin-medium'

PIPER_MODEL_URL = (
    f'https://huggingface.co/rhasspy/piper-voices/resolve/0c9c5d3/{PIPER_MODEL}.onnx'
)

PIPER_MODEL_HASH = '5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4'
PIPER_MODEL_PATH = (CACHE_PATH / PIPER_MODEL).with_suffix('.onnx')
PIPER_MODEL_JSON_PATH = (CACHE_PATH / PIPER_MODEL).with_suffix('.onnx.json')

PIPER_DOWNLOAD_NOTIFICATION_ID = 'speech_synthesis:download-piper'
