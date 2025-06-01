"""Handle speech recognition results and intents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.logger import logger
from ubo_app.store.main import store
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionIntent,
    SpeechRecognitionReportIntentDetectionAction,
    SpeechRecognitionReportSpeechAction,
    SpeechRecognitionStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from abstraction import (
        Recognition,
    )


@store.with_state(
    lambda state: (state.speech_recognition.status, state.speech_recognition.intents),
)
def handle_speech_recognition(
    data: tuple[SpeechRecognitionStatus, Sequence[SpeechRecognitionIntent]],
    recognition: Recognition,
) -> None:
    """Handle speech recognitions."""
    status, intents = data
    if status is SpeechRecognitionStatus.INTENTS_WAITING:
        if intent := next(
            (
                intent
                for intent in intents
                if (
                    intent.phrase.lower() == recognition.text.lower()
                    if isinstance(intent.phrase, str)
                    else recognition.text.lower()
                    in [phrase.lower() for phrase in intent.phrase]
                )
            ),
            None,
        ):
            logger.info(
                'Intent recognized',
                extra={
                    'engine_name': recognition.engine_name,
                    'text': recognition.text,
                    'intent': intent,
                },
            )
            store.dispatch(SpeechRecognitionReportIntentDetectionAction(intent=intent))
    elif status is SpeechRecognitionStatus.ASSISTANT_WAITING:
        logger.info(
            'Assistant command recognized',
            extra={
                'engine_name': recognition.engine_name,
                'text': recognition.text,
            },
        )
        store.dispatch(
            SpeechRecognitionReportSpeechAction(
                audio=recognition.audio,
                text=recognition.text,
                engine_name=recognition.engine_name,
            ),
        )
