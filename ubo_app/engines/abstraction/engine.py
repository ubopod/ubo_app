"""Base class for third-party engines."""

import abc


class EngineMixin(abc.ABC):
    """Base class for third-party engines."""

    def __init__(self, *, label: str | None = None) -> None:
        """Initialize the EngineMixin."""
        self._instance_label = label

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The name of the engine."""

    @property
    @abc.abstractmethod
    def label(self) -> str:
        """The label of the engine."""

    @property
    def instance_label(self) -> str:
        """The label of the engine instance."""
        return self.label if self._instance_label is None else self._instance_label
