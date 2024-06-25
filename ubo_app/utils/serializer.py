"""Contains the serialization functions for the immutable objects."""

import base64
from typing import Any

import dill
from immutable import Immutable


def add_type_field(
    obj: Immutable,
    serialized: dict[str, Any],
) -> dict[str, Any]:
    """Add the type field to the serialized object."""
    return {
        **serialized,
        '_type': base64.b64encode(dill.dumps(obj.__class__)).decode('utf-8'),
    }
