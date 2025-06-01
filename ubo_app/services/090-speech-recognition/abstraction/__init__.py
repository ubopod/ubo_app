"""Abstract classes for speech recognition and wake word detection."""

from .background_running_mixing import BackgroundRunningMixin
from .needs_setup_mixin import NeedsSetupMixin
from .speech_recognition_mixin import (
    PhraseRecognition,
    Recognition,
    SpeechRecognition,
    SpeechRecognitionMixin,
)
from .wake_word_recognition_mixin import WakeWordRecognitionMixin

__all__ = (
    'BackgroundRunningMixin',
    'NeedsSetupMixin',
    'PhraseRecognition',
    'Recognition',
    'SpeechRecognition',
    'SpeechRecognitionMixin',
    'WakeWordRecognitionMixin',
)
