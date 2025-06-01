"""Needs-Setup mixin abstract base class."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

from constants import ENGINE_ERROR_NOTIFICATION_ID
from typing_extensions import override

from ubo_app.colors import DANGER_COLOR
from ubo_app.store.main import store
from ubo_app.store.services.notifications import Notification, NotificationsAddAction
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionSetIsAssistantActiveAction,
    SpeechRecognitionSetIsIntentsActiveAction,
)

from .background_running_mixing import BackgroundRunningMixin

if TYPE_CHECKING:
    from ubo_app.store.services.speech_recognition import SpeechRecognitionEngineName


class NeedsSetupMixin(BackgroundRunningMixin, abc.ABC):
    """Base class for engines that require setup."""

    @override
    def __init__(
        self,
        *,
        name: SpeechRecognitionEngineName,
        label: str,
        not_setup_message: str,
    ) -> None:
        """Initialize the NeedsSetupMixin."""
        self.not_setup_message = not_setup_message
        super().__init__(name=name, label=label)

    @abc.abstractmethod
    def is_setup(self) -> bool:
        """Check if the engine is set up."""
        raise NotImplementedError

    @abc.abstractmethod
    def setup(self) -> None:
        """Perform the setup for the engine."""
        raise NotImplementedError

    @override
    def run(self) -> None:
        """Check if the engine is set up before running."""
        if not self.is_setup():
            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=ENGINE_ERROR_NOTIFICATION_ID.format(engine=self.name),
                        title='Speech Recognition',
                        content=self.not_setup_message,
                        color=DANGER_COLOR,
                    ),
                ),
                SpeechRecognitionSetIsIntentsActiveAction(is_active=False),
                SpeechRecognitionSetIsAssistantActiveAction(is_active=False),
            )
            return
        super().run()
