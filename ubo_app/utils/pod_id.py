"""Module for managing the pod ID."""

import pathlib
import random
import string
from typing import Literal, overload

from ubo_app.constants import INSTALLATION_PATH
from ubo_app.utils.eeprom import read_serial_number

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


def set_pod_id() -> None:
    """Set the pod ID."""
    serial_number = read_serial_number()
    available_letters = list(
        set(string.ascii_lowercase + string.digits + '-') - set('I1lO'),
    )

    try:
        random.seed(serial_number)
        # Generate 2 letters random id
        id = f'ubo-{"".join(random.sample(available_letters, 2))}'
        id_path.write_text(id)
    finally:
        random.seed()
