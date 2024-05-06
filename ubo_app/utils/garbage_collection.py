# ruff: noqa: BLE001, S112
"""Garbage collection investigation tools."""

from __future__ import annotations

import contextlib
import gc
import inspect
from sys import stdout
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import weakref
    from collections.abc import Callable

SHORT_PRINT_LENGTH = 60


def short_print(obj: object) -> None:
    """Print the object."""
    stdout.write(str(type(obj)))
    try:
        stdout.write(
            str(obj)[:SHORT_PRINT_LENGTH] + '...'
            if len(str(obj)) > SHORT_PRINT_LENGTH
            else str(obj),
        )
        stdout.write('\n')
    except Exception as exception:
        if isinstance(exception, KeyboardInterrupt):
            raise
        stdout.write('Failed to print object\n')
    stdout.flush()


def examine(
    obj: object,
    *,
    depth_limit: int,
    filter_: Callable[[object], bool] = lambda _: True,
    looking_for: str | None = None,
) -> None:
    """Examine the object."""
    island = [obj]
    to_check: list[tuple[object, int]] = [(obj, 1)]
    path = []

    while to_check:
        obj, depth = to_check.pop()
        if looking_for:
            while len(path) >= depth:
                path.pop()
            path.append(obj)
        with contextlib.suppress(Exception):
            if looking_for and looking_for in str(type(obj)):
                stdout.write('Found\n')
                stdout.flush()
                for i in path:
                    short_print(i)
                break
        try:
            referrers = [
                i
                for i in gc.get_referrers(obj)
                if i not in island
                and i not in to_check
                and i is not path
                and i is not island
                and i is not to_check
            ]
        except Exception:
            continue

        for i in referrers:
            island.append(i)
            if filter_(i):
                short_print(i)
            if depth < depth_limit:
                to_check.append((i, depth + 1))
        del referrers


def search_stack_for_instance(ref: weakref.ReferenceType) -> None:
    """Search the stack for an instance."""
    frames = inspect.stack()
    with contextlib.suppress(Exception):
        for frame in frames:
            local_vars = frame.frame.f_locals
            for var_name, var_value in local_vars.items():
                if var_value is ref():
                    stdout.write(
                        'Found instance'
                        + str(
                            {
                                'var_name': var_name,
                                'var_value': var_value,
                                'frame': frame,
                            },
                        )
                        + '\n',
                    )
                    stdout.flush()
