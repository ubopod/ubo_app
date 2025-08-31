"""Constants for the assistant module."""

import os

INTENTS_WAKE_WORD = os.environ.get('UBO_INTENTS_WAKE_WORD', 'hey pod')
ASSISTANT_WAKE_WORD = os.environ.get('UBO_ASSISTANT_WAKE_WORD', 'hey there')
ASSISTANT_END_WORD = os.environ.get('UBO_ASSISTANT_END_WORD', 'roger that')
ASSISTANT_DEBUG_PATH = os.environ.get('UBO_ASSISTANT_DEBUG_PATH')
DEFAULT_ASSISTANT_OLLAMA_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OLLAMA_MODEL',
    'gemma3:1b',
)
DEFAULT_ASSISTANT_GOOGLE_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_GOOGLE_MODEL',
    'gemini-2.5-flash-preview-05-20',
)
DEFAULT_ASSISTANT_OPENAI_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_OPENAI_MODEL',
    'gpt-4o',
)
DEFAULT_ASSISTANT_ANTHROPIC_MODEL = os.environ.get(
    'UBO_DEFAULT_ASSISTANT_ANTHROPIC_MODEL',
    'claude-3-opus-20240229',
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
OPENAI_API_KEY_PATTERN = '^sk-[a-zA-Z0-9]{32,}$'
