"""Registry of actions that can be bound to a trigger like an infrared remote key.

Services opt in by registering the no-argument actions they want to expose for
binding, each with a stable string ``key`` and a human-readable ``label``::

    register_bindable_action(
        'assistant:toggle',
        'Assistant: Toggle Listening',
        lambda ctx: AssistantToggleListeningAction(...),
    )

A binding stores only the stable ``key`` (e.g. on an ``InfraredDevice``); the
``factory`` is resolved at trigger time and called with a
:class:`BindableActionContext` so the produced action can carry trigger
metadata (protocol/scancode/device name). This keeps the binding decoupled from
the concrete action types, which stay owned by the registering service.

Labels must be unique because user interfaces present the labels and map the
chosen label back to its key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from ubo_app.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.main import UboAction


class BindableActionContext(NamedTuple):
    """Context passed to a bindable action factory when the binding fires."""

    protocol: str
    scancode: str
    device_name: str


class BindableAction(NamedTuple):
    """A registered action that can be bound to a trigger."""

    key: str
    label: str
    factory: Callable[[BindableActionContext], UboAction]


# Module-level singleton registry (insertion order is preserved for determinism).
_registry: dict[str, BindableAction] = {}


def register_bindable_action(
    key: str,
    label: str,
    factory: Callable[[BindableActionContext], UboAction],
    *,
    allow_reregister: bool = False,
) -> None:
    """Register a bindable action.

    Args:
        key: Stable unique identifier persisted by bindings (e.g. ``assistant:toggle``).
        label: Human-readable, unique label shown in the UI.
        factory: Builds the action from a :class:`BindableActionContext`.
        allow_reregister: If True, replace an existing entry with the same key.
            If False (default), raise when the key is already registered.

    Raises:
        ValueError: If the key is already registered (and not allowed to
            re-register), or if the label is already used by another key.

    """
    if key in _registry and not allow_reregister:
        msg = f"Bindable action '{key}' is already registered"
        raise ValueError(msg)

    for existing in _registry.values():
        if existing.label == label and existing.key != key:
            msg = (
                f"Bindable action label '{label}' is already used by "
                f"'{existing.key}'"
            )
            raise ValueError(msg)

    _registry[key] = BindableAction(key=key, label=label, factory=factory)
    logger.debug('Registered bindable action: %s (%s)', key, label)


def unregister_bindable_action(key: str) -> bool:
    """Unregister a bindable action.

    Returns:
        True if the key was found and removed, False otherwise.

    """
    if key in _registry:
        del _registry[key]
        logger.debug('Unregistered bindable action: %s', key)
        return True
    return False


def clear_all_bindable_actions() -> None:
    """Clear all registered bindable actions.

    Primarily useful for testing.
    """
    _registry.clear()
    logger.debug('Cleared all bindable actions')


def get_bindable_action(key: str) -> BindableAction | None:
    """Return the bindable action for *key*, or None if not registered."""
    return _registry.get(key)


def get_bindable_actions() -> list[BindableAction]:
    """Return all registered bindable actions in registration order."""
    return list(_registry.values())
