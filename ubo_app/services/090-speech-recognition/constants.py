"""Constants for the speech recognition service."""

from ubo_app.store.services.speech_recognition import SpeechRecognitionEngineName

OFFLINE_ENGINES: list[SpeechRecognitionEngineName] = [
    SpeechRecognitionEngineName.VOSK,
]
