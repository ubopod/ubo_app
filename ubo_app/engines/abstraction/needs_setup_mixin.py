"""Needs-Setup mixin abstract base class."""

from __future__ import annotations

import abc
from typing import final

from typing_extensions import override

from ubo_app.colors import DANGER_COLOR
from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.background_running_mixin import BackgroundRunningMixin
from ubo_app.engines.abstraction.engine import EngineMixin
from ubo_app.utils.async_ import create_task

ENGINE_ERROR_NOTIFICATION_ID = 'ubo:engine-error:{engine}'


class NeedsSetupMixin(EngineMixin, abc.ABC):
    """Base class for engines that require setup."""

    @override
    def __init__(self, *, label: str | None = None) -> None:
        """Initialize the NeedsSetupMixin."""
        super().__init__(label=label)
        if hasattr(self, 'run') and callable(self.run):
            self._original_run = self.run
            self.run = self._checked_run

    @property
    @abc.abstractmethod
    def not_setup_message(self) -> str:
        """The message to display when the engine is not set up."""

    @property
    @abc.abstractmethod
    def is_setup(self) -> bool:
        """Check if the engine is set up."""
        raise NotImplementedError

    @abc.abstractmethod
    async def _setup(self) -> None:
        """Perform the setup for the engine."""
        raise NotImplementedError

    @final
    def setup(self) -> None:
        """Set up the engine."""
        if isinstance(self, AIProviderMixin):
            from ubo_app.store.main import store
            from ubo_app.store.services.assistant import AssistantUpdateProvidersAction

            create_task(
                self._setup(),
                lambda task: task.add_done_callback(
                    lambda _: store.dispatch(AssistantUpdateProvidersAction()),
                ),
            )
        else:
            create_task(self._setup())

    def _checked_run(self) -> bool:
        """Check if the engine is set up before running."""
        if isinstance(self, BackgroundRunningMixin) and not self.is_setup:
            from ubo_app.store.main import store
            from ubo_app.store.services.notifications import (
                Notification,
                NotificationActionItem,
                NotificationsAddAction,
            )

            store.dispatch(
                NotificationsAddAction(
                    notification=Notification(
                        id=ENGINE_ERROR_NOTIFICATION_ID.format(engine=self.name),
                        title='Speech Recognition',
                        content=self.not_setup_message,
                        color=DANGER_COLOR,
                        actions=[
                            NotificationActionItem(
                                key='setup',
                                label='Set Up',
                                action=self.setup,
                                icon='󰒓',
                            ),
                        ],
                    ),
                ),
            )
            return False
        return self._original_run()
