"""Reusable form utilities for Docker apps that need secret key management."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
)
from ubo_app.utils import secrets

if TYPE_CHECKING:
    from collections.abc import Mapping

_ENTER_NEW = 'Enter new key'


class SecretKeyEntry(NamedTuple):
    """Metadata for one provider or channel key."""

    label: str
    env_var: str
    canonical: str
    match_substring: str


def discover_provider_secrets(
    match_substring: str,
    canonical: str,
) -> list[str]:
    """Return secret names that look like they belong to a given provider."""
    names = secrets.list_secrets()
    matches = {name for name in names if match_substring.lower() in name.lower()}
    if canonical in names:
        matches.add(canonical)
    return sorted(matches)


def existing_select_options(
    match_substring: str,
    canonical: str,
) -> list[str]:
    """Build the SELECT option labels for discovered provider secrets."""
    options: list[str] = []
    for name in discover_provider_secrets(match_substring, canonical):
        masked = secrets.read_covered_secret(name) or '<Not set>'
        options.append(f'{name} ({masked})')
    options.append(_ENTER_NEW)
    return options


def parse_select_choice(choice: str | None) -> str | None:
    """Extract the secret name from a SELECT option label."""
    if not choice or choice == _ENTER_NEW:
        return None
    return choice.split(' (', 1)[0]


def build_provider_fields(
    key: str,
    label: str,
    canonical: str,
    match_substring: str,
    *,
    required: bool,
) -> list[InputFieldDescription]:
    """Build the SELECT + PASSWORD + save-as fields for one provider/channel."""
    options = existing_select_options(match_substring, canonical)
    fields_: list[InputFieldDescription] = []
    has_existing = len(options) > 1
    if has_existing:
        fields_.append(
            InputFieldDescription(
                name=f'{key}__existing',
                label=f'{label} — existing key',
                type=InputFieldType.SELECT,
                options=options,
                description='Pick an existing key or choose "Enter new key".',
                required=required,
            ),
        )
    fields_.append(
        InputFieldDescription(
            name=f'{key}__new',
            label=f'{label} — new key',
            type=InputFieldType.PASSWORD,
            description='Only used when you chose "Enter new key" above.'
            if has_existing
            else f'Enter the {label} API key.',
            required=required and not has_existing,
        ),
    )
    fields_.append(
        InputFieldDescription(
            name=f'{key}__save_as',
            label=f'{label} — save as (optional)',
            type=InputFieldType.TEXT,
            description=f'Name to store the new key under (default: {canonical}).',
            default_value=canonical,
            required=False,
        ),
    )
    return fields_


def resolve_provider_result(
    data: Mapping[str, str],
    key: str,
    canonical: str,
) -> str | None:
    """Resolve one provider/channel's form values into a usable key value."""
    existing_choice = parse_select_choice(data.get(f'{key}__existing'))
    new_value = (data.get(f'{key}__new') or '').strip()
    save_as = (data.get(f'{key}__save_as') or '').strip() or canonical

    if existing_choice:
        value = secrets.read_secret(existing_choice)
        if value:
            return value
    if new_value:
        secrets.write_secret(key=save_as, value=new_value)
        return new_value
    return None


def is_checkbox_on(value: str | None) -> bool:
    """Interpret a CHECKBOX form value as a boolean.

    The web UI submits ``"on"`` for toggled switches.
    """
    return (value or '').strip().lower() in (
        'on', 'true', '1', 'yes', 'checked',
    )
