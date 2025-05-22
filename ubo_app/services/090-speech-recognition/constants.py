"""Constants for the Vosk speech recognition model."""

from ubo_app.constants import CACHE_PATH
from ubo_app.utils import IS_RPI_4

VOSK_MODEL = (
    'vosk-model-small-en-us-0.15' if IS_RPI_4 else 'vosk-model-en-us-0.22-lgraph'
)

VOSK_MODEL_URL = f'https://alphacephei.com/vosk/models/{VOSK_MODEL}.zip'

VOSK_MODEL_PATH = CACHE_PATH / VOSK_MODEL
VOSK_DOWNLOAD_PATH = VOSK_MODEL_PATH.with_suffix('.zip')

VOSK_DOWNLOAD_NOTIFICATION_ID = 'speech_recognition:download-vosk'
