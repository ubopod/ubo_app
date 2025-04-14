# ruff: noqa: D100, D101, D102, D103, D104, D107, N999
from ubo_app.constants import CACHE_PATH

VOSK_MODEL = 'vosk-model-en-us-0.22-lgraph'

VOSK_MODEL_URL = f'https://alphacephei.com/vosk/models/{VOSK_MODEL}.zip'

VOSK_MODEL_PATH = CACHE_PATH / VOSK_MODEL
VOSK_DOWNLOAD_PATH = VOSK_MODEL_PATH.with_suffix('.zip')

VOSK_DOWNLOAD_NOTIFICATION_ID = 'speech_recognition:download-vosk'
