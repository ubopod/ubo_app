"""Constants for the assistant module."""

import os

from ubo_app.constants import DATA_PATH

INTENTS_WAKE_WORD = os.environ.get('UBO_INTENTS_WAKE_WORD', 'short voice command')
ASSISTANT_QUICK_CHAT_WAKE_PHRASE = os.environ.get(
    'UBO_ASSISTANT_QUICK_CHAT_WAKE_PHRASE',
    'hey quick question',
)
ASSISTANT_CONVERSATION_WAKE_WORD = os.environ.get(
    'UBO_ASSISTANT_CONVERSATION_WAKE_WORD',
    "let's have a conversation",
)
ASSISTANT_CONVERSATION_END_PHRASES: tuple[str, ...] = tuple(
    phrase.strip()
    for phrase in os.environ.get(
        'UBO_ASSISTANT_CONVERSATION_END_PHRASES',
        "i am done talking|i'm done talking",
    ).split('|')
    if phrase.strip()
)
ASSISTANT_STOP_TALKING_PHRASE = os.environ.get(
    'UBO_ASSISTANT_STOP_TALKING_PHRASE',
    'okay enough',
)
# Hands the utterance to Home Assistant's voice pipeline over Wyoming instead of
# the on-device assistant — see ``WakeMode.HOME_ASSISTANT``.
HOME_ASSISTANT_WAKE_PHRASE = os.environ.get(
    'UBO_HOME_ASSISTANT_WAKE_PHRASE',
    'hey home assistant',
)
ASSISTANT_DEFAULT_SILENCE_TIMEOUT_SECONDS: float = float(
    os.environ.get('UBO_ASSISTANT_DEFAULT_SILENCE_TIMEOUT_SECONDS', '2.0'),
)
# Conversation mode tolerates long mid-sentence pauses: the turn completes on an
# end-of-turn phrase OR after this many seconds of continuous silence.
ASSISTANT_CONVERSATION_SILENCE_TIMEOUT_SECONDS: float = float(
    os.environ.get('UBO_ASSISTANT_CONVERSATION_SILENCE_TIMEOUT_SECONDS', '5.0'),
)
ASSISTANT_DEBUG_PATH = os.environ.get('UBO_ASSISTANT_DEBUG_PATH')
DEFAULT_LLM_OLLAMA_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OLLAMA_MODEL',
    'liquidai/lfm2.5-350m',
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
DEFAULT_LLM_GENERIC_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_GENERIC_LLM_MODEL',
    'gpt-4.1',
)
DEFAULT_LLM_ANTHROPIC_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_ANTHROPIC_MODEL',
    'claude-sonnet-4-5',
)
DEFAULT_LLM_QWEN_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_QWEN_MODEL',
    'qwen-plus',
)
DEFAULT_LLM_DEEPSEEK_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_DEEPSEEK_MODEL',
    'deepseek-chat',
)
DEFAULT_LLM_OPENROUTER_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OPENROUTER_MODEL',
    'openai/gpt-4o-mini',
)
DEFAULT_LLM_MISTRAL_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_MISTRAL_MODEL',
    'mistral-small-latest',
)
DEFAULT_LLM_VENICE_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_MODEL',
    'llama-3.3-70b',
)
DEFAULT_VENICE_STT_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_STT_MODEL',
    'nvidia/parakeet-tdt-0.6b-v3',
)
DEFAULT_VENICE_TTS_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_TTS_MODEL',
    'tts-kokoro',
)
DEFAULT_VENICE_TTS_VOICE = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_TTS_VOICE',
    # Venice serves Kokoro voices; default to the Kokoro default so the voice
    # picker (which mirrors the Kokoro catalog) can highlight it.
    'af_heart',
)
DEFAULT_VENICE_IMAGE_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_VENICE_IMAGE_MODEL',
    'venice-sd35',
)

DEFAULT_MISTRAL_TTS_VOICE = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_MISTRAL_TTS_VOICE',
    # Mistral TTS requires a voice and its voices are live-fetched (no static
    # catalog). The hosted API expects ``{lang}_{name}_{style}`` preset slugs
    # (e.g. ``en_paul_neutral``) — NOT the self-hosted-only ``casual_male``,
    # which the hosted API rejects with 404. Used until the user picks one from
    # the picker; override per-deployment if a different preset is preferred.
    'en_paul_neutral',
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
# Accept both the modern ``sk_<alphanumeric>`` keys and the legacy bare-hex
# keys. Kept deliberately permissive — over-strict patterns reject valid keys
# (the legacy ``^[a-f0-9]{64}$`` blocked every ``sk_`` key); the API is the
# real validator.
ELEVENLABS_API_KEY_PATTERN = '^(sk_)?[a-zA-Z0-9]{32,}$'
ELEVENLABS_VOICE_ID = 'elevenlabs_voice_id'
ELEVENLABS_VOICE_ID_PATTERN = '^[a-zA-Z0-9-_]{20,}$'

BRAVE_SEARCH_API_KEY_SECRET_ID = 'brave_search_api_key'  # noqa: S105
BRAVE_SEARCH_API_KEY_PATTERN = '^BS[a-zA-Z0-9-_]{20,}$'

VOSK_DOWNLOAD_NOTIFICATION_ID = 'assistant:download-vosk'
MOONSHINE_DOWNLOAD_NOTIFICATION_ID = 'assistant:download-moonshine'

OLLAMA_SETUP_NOTIFICATION_ID = 'assistant:ollama:setup'
OLLAMA_RAM_LIMIT_NOTIFICATION_ID = 'assistant:ollama:ram-limit'

OLLAMA_ONPREM_URL_SECRET_ID = 'ollama_onprem_url'  # noqa: S105
OLLAMA_ONPREM_URL_PATTERN = r'^https?://[a-zA-Z0-9.-]+(:[0-9]+)?/?$'
OLLAMA_ONPREM_SETUP_NOTIFICATION_ID = 'assistant:ollama_onprem:setup'

# Canonical "active copy" keys — the assistant subprocess reads these. The
# core copies the selected named provider's credentials into them on select.
GENERIC_LLM_BASE_URL_SECRET_ID = 'generic_llm_base_url'  # noqa: S105
GENERIC_LLM_API_KEY_SECRET_ID = 'generic_llm_api_key'  # noqa: S105
GENERIC_LLM_MODEL_SECRET_ID = 'generic_llm_model'  # noqa: S105
GENERIC_LLM_BASE_URL_PATTERN = r'^https?://\S+$'
GENERIC_LLM_SETUP_NOTIFICATION_ID = 'assistant:generic_llm:setup'
# Per-provider credential keys for named generic LLM providers. Provider ids
# are slugs limited to [a-z0-9_] so the resulting keys stay dotenv-safe.
GENERIC_LLM_PROVIDER_BASE_URL_SECRET_TEMPLATE = 'generic_llm_{provider_id}_base_url'  # noqa: S105
GENERIC_LLM_PROVIDER_API_KEY_SECRET_TEMPLATE = 'generic_llm_{provider_id}_api_key'  # noqa: S105
GENERIC_LLM_PROVIDER_MODEL_SECRET_TEMPLATE = 'generic_llm_{provider_id}_model'  # noqa: S105

PIPER_MODEL = 'en/en_US/kristin/medium/en_US-kristin-medium'
PIPER_MODEL_URL = (
    f'https://huggingface.co/rhasspy/piper-voices/resolve/0c9c5d3/{PIPER_MODEL}.onnx'
)
PIPER_MODEL_HASH = '5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4'
PIPER_MODEL_PATH = (DATA_PATH / PIPER_MODEL).with_suffix('.onnx')
PIPER_MODEL_JSON_PATH = (DATA_PATH / PIPER_MODEL).with_suffix('.onnx.json')
# The Piper download flow uses two notification ids:
#  * NOTIFICATION — the on-screen notification. STICKY while the download
#    runs, overwritten in place by the FLASH on completion (sticky and
#    flash deliberately share this id). Both are user-dismissable.
#  * PROGRESS — the BACKGROUND status-bar progress wheel. Its own id so it
#    survives the user dismissing the sticky / navigating away, and keeps
#    advancing until the download finishes.
PIPER_DOWNLOAD_NOTIFICATION_ID = 'speech_synthesis:download-piper'
PIPER_DOWNLOAD_PROGRESS_NOTIFICATION_ID = 'speech_synthesis:download-piper:progress'

# Kokoro mirrors the Piper download-notification pattern: one on-screen
# notification (STICKY → FLASH) that shares an id between start and
# completion, plus a separate BACKGROUND id that drives the status-bar
# progress wheel and survives navigation / dismiss of the sticky.
KOKORO_DOWNLOAD_NOTIFICATION_ID = 'speech_synthesis:download-kokoro'
KOKORO_DOWNLOAD_PROGRESS_NOTIFICATION_ID = 'speech_synthesis:download-kokoro:progress'

DEEPGRAM_API_KEY_SECRET_ID = 'deepgram_api_key'  # noqa: S105
DEEPGRAM_API_KEY_PATTERN = '^[a-f0-9]{40}$'

CEREBRAS_API_KEY_SECRET_ID = 'cerebras_api_key'  # noqa: S105
CEREBRAS_API_KEY_PATTERN = '^csk-[a-zA-Z0-9-_]{40,}$'

ANTHROPIC_API_KEY_SECRET_ID = 'anthropic_api_key'  # noqa: S105
ANTHROPIC_API_KEY_PATTERN = r'^sk-ant-[a-zA-Z0-9_-]{40,}$'

QWEN_API_KEY_SECRET_ID = 'qwen_api_key'  # noqa: S105
QWEN_API_KEY_PATTERN = r'^sk-[a-zA-Z0-9._-]{32,}$'

DEEPSEEK_API_KEY_SECRET_ID = 'deepseek_api_key'  # noqa: S105
DEEPSEEK_API_KEY_PATTERN = r'^sk-[a-zA-Z0-9]{32,}$'

OPENROUTER_API_KEY_SECRET_ID = 'openrouter_api_key'  # noqa: S105
OPENROUTER_API_KEY_PATTERN = r'^sk-or-v1-[a-f0-9]{64}$'

MISTRAL_API_KEY_SECRET_ID = 'mistral_api_key'  # noqa: S105
MISTRAL_API_KEY_PATTERN = r'^[a-zA-Z0-9]{32}$'

VENICE_API_KEY_SECRET_ID = 'venice_api_key'  # noqa: S105
VENICE_API_KEY_PATTERN = r'^[a-zA-Z0-9_-]{20,}$'
VENICE_BASE_URL = 'https://api.venice.ai/api/v1'

ASSEMBLYAI_API_KEY_SECRET_ID = 'assemblyai_api_key'  # noqa: S105
ASSEMBLYAI_API_KEY_PATTERN = '^[a-f0-9]{32}$'

RIME_API_KEY_SECRET_ID = 'rime_api_key'  # noqa: S105
RIME_API_KEY_PATTERN = '^[a-zA-Z0-9-_]{32,}$'
