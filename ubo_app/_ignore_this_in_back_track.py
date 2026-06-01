from __future__ import annotations

import importlib
import sys
from importlib._bootstrap import (
    _find_and_load_unlocked as ignore_this_in_backtraack,  # pyright: ignore[reportAttributeAccessIssue]
)
from typing import TYPE_CHECKING

from ubo_app.constants import PACKAGE_NAME
from ubo_app.utils.service import ServiceUnavailableError, get_service

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType


def _ignore_this_in_backtraack(name: str, import_: Callable) -> ModuleType:
    # Customized find_and_load_unlocked to handle service thread module isolation.
    #
    # Never prefix ``ubo_app.*`` modules: they are shared singletons (the store,
    # menus, view computation, …) and ``UboServiceFinder`` already excludes them
    # from service isolation (``service_thread.py``: ``if fullname.startswith(
    # PACKAGE_NAME): return None``). Prefixing them here is inconsistent with the
    # finder and, for a deferred import on a service/scheduler thread, forces a
    # fresh off-main-thread load of ``ubo_app.store.main`` whose module-level
    # guard then raises ``Store should be created in the main thread`` (or, if
    # the load is re-entrant, ``cannot import name 'store'``).
    parent = name.rpartition('.')[0]
    if parent and not name.startswith(PACKAGE_NAME):
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
