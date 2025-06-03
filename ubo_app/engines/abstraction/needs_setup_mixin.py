"""Needs-Setup mixin abstract base class."""

from __future__ import annotations

import abc

from typing_extensions import override

from ubo_app.colors import DANGER_COLOR
from ubo_app.engines.abstraction.background_running_mixin import BackgroundRunningMixin
from ubo_app.store.main import store
from ubo_app.store.services.notifications import Notification, NotificationsAddAction

ENGINE_ERROR_NOTIFICATION_ID = 'speech_recognition:engine-error:{engine}'


class NeedsSetupMixin(BackgroundRunningMixin, abc.ABC):
    """Base class for engines that require setup."""

    @override
    def __init__(
        self,
        *,
        name: str,
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
    def run(self) -> bool:
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
            )
            return False
        return super().run()
