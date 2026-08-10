"""Collect a bindable action's parameters, as a follow-up prompt.

A parameter's choices generally aren't knowable until the moment of asking — the
kiosk's dashboards are user-managed, for instance — but a Web UI form's SELECT
options are serialized into the prompt when it is created and the browser has no
way to fetch more later. So the parameters are asked for in a *second* prompt,
opened once the action is known. This is the same shape the wake-trigger editor
(``090-speech-recognition/wake_menu.py``) and the WiFi and OpenClaw wizards use,
and the Web UI reducer deliberately keeps the hotspot up between steps.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ubo_app.logger import logger
from ubo_app.store.core.bindable_actions import encode_binding
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.utils.input import ubo_input

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ubo_app.store.core.bindable_actions import BindableAction, BindableParameter


def _field(
    parameter: BindableParameter,
    options: list[str] | None,
    default: str | None,
) -> InputFieldDescription:
    return InputFieldDescription(
        name=parameter.name,
        label=parameter.label,
        type=parameter.field_type,
        description=parameter.description,
        options=options,
        default_value=default,
        required=True,
    )


def _build_fields(
    action: BindableAction,
    defaults: Mapping[str, str],
) -> tuple[list[InputFieldDescription], dict[str, dict[str, str]]] | None:
    """Build the form fields, and the label→value maps needed to read it back.

    Each SELECT shows labels and maps the choice back, mirroring how the action
    dropdown itself resolves a label to a key. The maps are per parameter
    because two parameters can offer the same label for different values.

    Returns None when a parameter has nothing to offer — there is no binding to
    make, and an empty dropdown would be a dead end.
    """
    label_to_value: dict[str, dict[str, str]] = {}
    fields: list[InputFieldDescription] = []
    for parameter in action.parameters:
        if parameter.options is None:
            fields.append(_field(parameter, None, defaults.get(parameter.name)))
            continue
        choices = list(parameter.options())
        if not choices:
            logger.warning(
                'Bindable action parameter has no choices to offer',
                extra={'action_key': action.key, 'parameter': parameter.name},
            )
            return None
        label_to_value[parameter.name] = {label: value for value, label in choices}
        current = defaults.get(parameter.name)
        selected = next(
            (label for value, label in choices if value == current),
            choices[0][1],
        )
        fields.append(_field(parameter, [label for _value, label in choices], selected))
    return fields, label_to_value


def _read_value(
    action: BindableAction,
    parameter: BindableParameter,
    raw: str,
    label_to_value: dict[str, dict[str, str]],
) -> str | None:
    """Turn one submitted field into the value to store, or None if unusable."""
    if parameter.name in label_to_value:
        value = label_to_value[parameter.name].get(raw)
        if value is None:
            logger.warning(
                'Unknown option selected for bindable action parameter',
                extra={
                    'action_key': action.key,
                    'parameter': parameter.name,
                    'selected': raw,
                },
            )
        return value
    if not raw and parameter.field_type is not InputFieldType.CHECKBOX:
        logger.warning(
            'Bindable action parameter left empty',
            extra={'action_key': action.key, 'parameter': parameter.name},
        )
        return None
    return raw


async def prompt_for_parameters(
    action: BindableAction,
    defaults: Mapping[str, str] | None = None,
) -> str | None:
    """Ask for *action*'s parameters and return the binding string to store.

    Returns the bare key without prompting when the action declares no
    parameters — which is every action but a handful — and ``None`` when the
    user cancels, so a caller can abandon rather than save a half-configured
    binding.

    ``defaults`` pre-selects values when an existing binding is being edited.
    """
    if not action.parameters:
        return action.key

    built = _build_fields(action, defaults or {})
    if built is None:
        return None
    fields, label_to_value = built

    try:
        _, result = await ubo_input(
            prompt=action.label,
            descriptions=[WebUIInputDescription(fields=fields)],
        )
    except asyncio.CancelledError:
        return None
    if result is None:
        return None

    parameters: dict[str, str] = {}
    for parameter in action.parameters:
        raw = (result.data.get(parameter.name, '') or '').strip()
        value = _read_value(action, parameter, raw, label_to_value)
        if value is None:
            return None
        parameters[parameter.name] = value

    return encode_binding(action.key, parameters)
