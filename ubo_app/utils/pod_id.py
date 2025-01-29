"""Module for managing the pod ID."""

import pathlib
from typing import Literal, overload

from ubo_app.constants import INSTALLATION_PATH

id_path = pathlib.Path(INSTALLATION_PATH) / 'pod-id'


@overload
def get_pod_id(*, with_default: Literal[True]) -> str: ...
@overload
def get_pod_id() -> str | None: ...


def get_pod_id(*, with_default: bool = False) -> str | None:
    """Return the pod ID."""
    try:
        return id_path.read_text().strip()
    except FileNotFoundError:
        if with_default:
            return 'ubo-__'
        return None


def set_pod_id(pod_id: str) -> None:
    """Set the pod ID."""
    id_path.write_text(pod_id)
