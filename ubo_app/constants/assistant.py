"""Constants for the assistant module."""

import os

from ubo_app.constants import CONFIG_PATH, DATA_PATH

INTENTS_WAKE_WORD = os.environ.get('UBO_INTENTS_WAKE_WORD', 'short voice command')
ASSISTANT_WAKE_WORD = os.environ.get('UBO_ASSISTANT_WAKE_WORD', 'can you help me')
ASSISTANT_END_WORD = os.environ.get('UBO_ASSISTANT_END_WORD', 'roger that')
ASSISTANT_DEBUG_PATH = os.environ.get('UBO_ASSISTANT_DEBUG_PATH')
DEFAULT_LLM_OLLAMA_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OLLAMA_MODEL',
    'gemma3:1b',
)
DEFAULT_LLM_GOOGLE_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_GOOGLE_MODEL',
    'gemini-2.5-flash-preview-05-20',
)
DEFAULT_LLM_OPENAI_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OPENAI_MODEL',
    'gpt-4o',
)
DEFAULT_LLM_GROK_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_GROK_MODEL',
    'grok-4-0709',
)
DEFAULT_LLM_CEREBRAS_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_CEREBRAS_MODEL',
    'qwen-3-235b-a22b-instruct-2507',
)
DEFAULT_LLM_OLLAMA_ONPREM_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OLLAMA_ONPREM_MODEL',
    'granite3.3:8b',
)

GOOGLE_API_KEY_SECRET_ID = 'google_api_key'  # noqa: S105
GOOGLE_API_KEY_PATTERN = '^AIza[0-9A-Za-z\\-_]{35}$'

GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_SECRET_ID = 'google_cloud_service_account_key'  # noqa: S105
GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY_PATTERN = """{
  "type": "service_account",
  "project_id": "[a-z][a-z0-9-]+",
  "private_key_id": "[a-z0-9]{40}",
  "private_key": "-----BEGIN PRIVATE KEY-----\\\\n([a-zA-Z0-9+/=\\\\n]+)\\\\n-----END \
PRIVATE KEY-----\\\\n",
  "client_email": "[a-z0-9._%+-]+@[a-z0-9-]+\\.iam\\.gserviceaccount\\.com",
  "client_id": "[0-9]{12,}",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/[a-z0-9-]+%40[a-z0-9-]+\\.iam\\.gserviceaccount\\.com",
  "universe_domain": "googleapis.com"
}"""

OPENAI_API_KEY_SECRET_ID = 'openai_api_key'  # noqa: S105
OPENAI_API_KEY_PATTERN = '^sk-[a-zA-Z0-9-_]{32,}$'

GROK_API_KEY_SECRET_ID = 'grok_api_key'  # noqa: S105
GROK_API_KEY_PATTERN = '^xai-[a-zA-Z0-9]{80}$'

ELEVENLABS_API_KEY_SECRET_ID = 'elevenlabs_api_key'  # noqa: S105
ELEVENLABS_API_KEY_PATTERN = '^[a-f0-9]{64}$'
ELEVENLABS_VOICE_ID = 'elevenlabs_voice_id'
ELEVENLABS_VOICE_ID_PATTERN = '^[a-zA-Z0-9-_]{20,}$'

BRAVE_SEARCH_API_KEY_SECRET_ID = 'brave_search_api_key'  # noqa: S105
BRAVE_SEARCH_API_KEY_PATTERN = '^BS[a-zA-Z0-9-_]{20,}$'

VOSK_MODEL = 'vosk-model-small-en-us-0.15'
VOSK_MODEL_URL = f'https://alphacephei.com/vosk/models/{VOSK_MODEL}.zip'
VOSK_MODEL_PATH = DATA_PATH / VOSK_MODEL
VOSK_DOWNLOAD_PATH = VOSK_MODEL_PATH.with_suffix('.zip')
VOSK_DOWNLOAD_NOTIFICATION_ID = 'assistant:download-vosk'

OLLAMA_SETUP_NOTIFICATION_ID = 'assistant:ollama:setup'

OLLAMA_ONPREM_URL_SECRET_ID = 'ollama_onprem_url'  # noqa: S105
OLLAMA_ONPREM_URL_PATTERN = r'^https?://[a-zA-Z0-9.-]+(:[0-9]+)?/?$'
OLLAMA_ONPREM_SETUP_NOTIFICATION_ID = 'assistant:ollama_onprem:setup'

PIPER_MODEL = 'en/en_US/kristin/medium/en_US-kristin-medium'
PIPER_MODEL_URL = (
    f'https://huggingface.co/rhasspy/piper-voices/resolve/0c9c5d3/{PIPER_MODEL}.onnx'
)
PIPER_MODEL_HASH = '5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4'
PIPER_MODEL_PATH = (DATA_PATH / PIPER_MODEL).with_suffix('.onnx')
PIPER_MODEL_JSON_PATH = (DATA_PATH / PIPER_MODEL).with_suffix('.onnx.json')
PIPER_DOWNLOAD_NOTIFICATION_ID = 'speech_synthesis:download-piper'

PICOVOICE_ACCESS_KEY_SECRET_ID = 'picovoice_access_key'  # noqa: S105

DEEPGRAM_API_KEY_SECRET_ID = 'deepgram_api_key'  # noqa: S105
DEEPGRAM_API_KEY_PATTERN = '^[a-f0-9]{40}$'

CEREBRAS_API_KEY_SECRET_ID = 'cerebras_api_key'  # noqa: S105
CEREBRAS_API_KEY_PATTERN = '^csk-[a-zA-Z0-9-_]{40,}$'

ASSEMBLYAI_API_KEY_SECRET_ID = 'assemblyai_api_key'  # noqa: S105
ASSEMBLYAI_API_KEY_PATTERN = '^[a-f0-9]{32}$'

RIME_API_KEY_SECRET_ID = 'rime_api_key'  # noqa: S105
RIME_API_KEY_PATTERN = '^[a-zA-Z0-9-_]{32,}$'


ASSISTANT_MCP_SERVERS_PATH = CONFIG_PATH / 'assistant_mcp_servers'
