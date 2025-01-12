"""Module for managing the pod ID."""

import pathlib

from ubo_app.constants import INSTALLATION_PATH

id_path = pathlib.Path(INSTALLATION_PATH) / 'pod-id'


def get_pod_id() -> str | None:
    """Return the pod ID."""
    try:
        return id_path.read_text().strip()
    except FileNotFoundError:
        return None


def set_pod_id(pod_id: str) -> None:
    """Set the pod ID."""
    id_path.write_text(pod_id)
