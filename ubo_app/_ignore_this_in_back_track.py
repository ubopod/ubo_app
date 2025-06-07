from __future__ import annotations

import importlib
import sys
from importlib._bootstrap import (
    _find_and_load_unlocked as ignore_this_in_backtraack,  # pyright: ignore[reportAttributeAccessIssue]
)
from typing import TYPE_CHECKING

from ubo_app.utils.service import ServiceUnavailableError, get_service

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType


def _ignore_this_in_backtraack(name: str, import_: Callable) -> ModuleType:
    # Customized find_and_load_unlocked to handle service thread module isolation.
    parent = name.rpartition('.')[0]
    if parent:
        try:
            service = get_service()
        except ServiceUnavailableError:
            pass
        else:
            if service.is_alive():
                if f'{service.service_uid}:{parent}' in sys.modules:
                    name = f'{service.service_uid}:{name}'
                elif parent not in sys.modules:
                    import_(parent)
                    if f'{service.service_uid}:{parent}' in sys.modules:
                        name = f'{service.service_uid}:{name}'
    return ignore_this_in_backtraack(
        name,
        import_,
    )


# This is dirty hack to process module names and prefix them with service UID before
# they are queried from sys.modules. Unfortunately, importlib does not provide a hook
# for this and we have to override the internal function.
importlib._bootstrap._find_and_load_unlocked = _ignore_this_in_backtraack  # noqa: SLF001 # pyright: ignore[reportAttributeAccessIssue]
