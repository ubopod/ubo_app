"""Import modules from a hyphenated service directory without leaking.

Service directories are named ``NNN-name``, which is not an importable package
path, and service modules import their siblings by **bare name** (``import ha``,
``from menu import init_menu``). The real service loader supports that by putting
the service directory on ``sys.path``; a test has to do the same.

That creates two hazards, and they pull in opposite directions:

1. **Bare aliases collide.** ``040-sensors`` and ``050-mqtt`` both have a
   ``menu.py``; ``090-infrared`` and ``040-sensors`` both have an ``ha.py``;
   every service has a ``setup.py``. An alias left in ``sys.modules`` silently
   becomes the module the *next* service imports.

2. **Purging too much breaks class identity.** The obvious fix — delete
   everything the import pulled in — also evicts ``ubo_app.store.services.*``.
   A later test re-imports those and gets *new* class objects, so an
   ``isinstance`` check against an action some service built starts failing.
   Only when files run together, and only in some orders.

So this loader evicts exactly the service-local modules, before *and* after the
import, and never touches ``ubo_app.*`` or anything installed. Store types stay
loaded once for the whole session, which is what keeps class identity stable.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import ubo_app

if TYPE_CHECKING:
    from types import ModuleType

SERVICES_ROOT = (Path(ubo_app.__file__).parent / 'services').resolve()


def _is_service_module(module: ModuleType) -> bool:
    """Whether a module was loaded out of any service directory."""
    file = getattr(module, '__file__', None)
    if not file:
        return False
    try:
        return SERVICES_ROOT in Path(file).resolve().parents
    except (OSError, ValueError):  # pragma: no cover - defensive
        return False


def _evict_service_modules() -> None:
    """Drop every bare alias currently pointing at a service module.

    Without this an already-cached alias short-circuits the import and hands
    back another service's module.
    """
    for name, module in list(sys.modules.items()):
        # ':' marks a running service's own registration — `UboServiceFinder`
        # keys them as `{service_uid}:{fullname}` — which is not a bare alias
        # and must survive.
        if '.' in name or ':' in name or not _is_service_module(module):
            continue
        del sys.modules[name]


def load_service_modules(service_dir: Path, *names: str) -> tuple[ModuleType, ...]:
    """Import `names` from `service_dir`, leaving `sys.modules` as it was found.

    The returned module objects stay usable — the caller's reference keeps them
    alive — but their bare aliases are gone, so the next service to be loaded
    gets its own files.
    """
    service_dir = Path(service_dir).resolve()

    _evict_service_modules()
    sys.path.insert(0, str(service_dir))
    try:
        modules = tuple(importlib.import_module(name) for name in names)
    finally:
        sys.path.remove(str(service_dir))
        _evict_service_modules()

    return modules
