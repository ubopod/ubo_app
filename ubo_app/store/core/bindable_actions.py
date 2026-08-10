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

An action may also declare :class:`BindableParameter` s, for the cases a flat
key can't reach — a value drawn from a set that only exists at runtime, or one
that isn't drawn from a set at all. The user fills them in when creating the
binding, and the values travel *with* the stored key::

    'kiosk:set-output?port=hdmi_a_2&target=dash:a1b2c3d4'

so a binding stays a single string and nothing about how bindings are stored or
serialized has to change. :func:`encode_binding` and :func:`decode_binding` are
the only two places that know the encoding; a key stored before parameters
existed decodes to ``(key, {})`` and keeps working.

Parameters are *not* a replacement for registering several keys. Register one
key per option when the options are a flat list of things the user named (the
per-device ``infrared:send:*`` actions); reach for parameters when the entries
would otherwise be a product of two axes, or a continuous value.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import parse_qsl, urlencode

from ubo_app.logger import logger
from ubo_app.store.input.types import InputFieldType

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ubo_app.store.main import UboAction

# Separates a binding's key from its url-encoded parameters.
PARAMETER_SEPARATOR = '?'

_NO_PARAMETERS: Mapping[str, str] = MappingProxyType({})


class BindableParameter(NamedTuple):
    """One value a bindable action needs, collected when the binding is created.

    ``options`` is a callable rather than a list because the choices are usually
    only knowable at prompt time — the kiosk's dashboards, for instance, are
    user-managed. It returns ``(stored value, displayed label)`` pairs; the label
    is what the dropdown shows, mirroring how the action dropdown itself maps a
    chosen label back to a key. Leave it ``None`` for a free-text/numeric
    ``field_type``.
    """

    name: str
    label: str
    field_type: InputFieldType = InputFieldType.SELECT
    options: Callable[[], Sequence[tuple[str, str]]] | None = None
    description: str | None = None


class BindableActionContext(NamedTuple):
    """Context passed to a bindable action factory when the binding fires."""

    protocol: str
    scancode: str
    device_name: str
    # The values collected for the action's declared ``parameters``, empty for
    # the (majority) of actions that declare none. Carried here rather than as a
    # second factory argument so every existing factory keeps its signature.
    parameters: Mapping[str, str] = _NO_PARAMETERS


class BindableAction(NamedTuple):
    """A registered action that can be bound to a trigger."""

    key: str
    label: str
    factory: Callable[[BindableActionContext], UboAction]
    parameters: Sequence[BindableParameter] = ()


# Module-level singleton registry (insertion order is preserved for determinism).
_registry: dict[str, BindableAction] = {}


def register_bindable_action(
    key: str,
    label: str,
    factory: Callable[[BindableActionContext], UboAction],
    *,
    parameters: Sequence[BindableParameter] = (),
    allow_reregister: bool = False,
) -> None:
    """Register a bindable action.

    Args:
        key: Stable unique identifier persisted by bindings (e.g. ``assistant:toggle``).
        label: Human-readable, unique label shown in the UI.
        factory: Builds the action from a :class:`BindableActionContext`.
        parameters: Values to collect from the user when a binding is created;
            they reach the factory as ``context.parameters``.
        allow_reregister: If True, replace an existing entry with the same key.
            If False (default), raise when the key is already registered.

    Raises:
        ValueError: If the key contains :data:`PARAMETER_SEPARATOR`, if the key
            is already registered (and not allowed to re-register), or if the
            label is already used by another key.

    """
    if PARAMETER_SEPARATOR in key:
        msg = (
            f"Bindable action key '{key}' may not contain "
            f"'{PARAMETER_SEPARATOR}' — it separates a stored binding's key "
            f'from its parameters'
        )
        raise ValueError(msg)

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

    _registry[key] = BindableAction(
        key=key,
        label=label,
        factory=factory,
        parameters=tuple(parameters),
    )
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


def encode_binding(key: str, parameters: Mapping[str, str]) -> str:
    """Return the string a binding stores for *key* with *parameters*.

    An action with no parameters encodes to its bare key, so the vast majority
    of bindings are byte-identical to what they were before parameters existed.
    Parameters are sorted so the same choices always produce the same string —
    which is what lets callers compare and deduplicate bindings by value.
    """
    if not parameters:
        return key
    return f'{key}{PARAMETER_SEPARATOR}{urlencode(sorted(parameters.items()))}'


def decode_binding(stored: str) -> tuple[str, dict[str, str]]:
    """Split a stored binding into its key and parameters.

    A binding stored before parameters existed has no separator and yields an
    empty mapping, which is why no persisted data needed migrating.
    """
    key, separator, query = stored.partition(PARAMETER_SEPARATOR)
    if not separator:
        return key, {}
    return key, dict(parse_qsl(query, keep_blank_values=True))


def resolve_binding(stored: str) -> tuple[BindableAction, dict[str, str]] | None:
    """Return the action and parameters a stored binding refers to, or None.

    None means the key isn't registered — the service that owned it is disabled,
    or the thing it referred to is gone. Callers log and skip.
    """
    key, parameters = decode_binding(stored)
    action = _registry.get(key)
    if action is None:
        return None
    return action, parameters
