"""Constants for the speech recognition service."""

from ubo_app.store.services.speech_recognition import SpeechRecognitionEngineName

OFFLINE_ENGINES: list[SpeechRecognitionEngineName] = [
    SpeechRecognitionEngineName.VOSK,
]

# Seconds to keep listening for a short voice command after the wake word
# before giving up and returning to idle.
INTENTS_LISTENING_TIMEOUT_SECONDS = 10
