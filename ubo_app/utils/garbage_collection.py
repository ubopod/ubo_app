# ruff: noqa: BLE001, S112
"""Garbage collection investigation tools."""

from __future__ import annotations

import contextlib
import gc
import inspect
import sys
import traceback
import types
from sys import stdout
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import weakref
    from collections.abc import Callable

SHORT_PRINT_LENGTH = 420


def short_print(depth: int, obj: object) -> None:
    """Print the object."""
    stdout.write(str(depth) + ': ' + str(type(obj)))
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
                    short_print(depth, i)
                break
        try:
            referrers = [
                i
                for i in gc.get_referrers(obj)
                if i not in island
                and i is not path
                and i is not island
                and i is not to_check
            ]
        except Exception:
            continue

        for i in referrers:
            island.append(i)
            if filter_(i):
                short_print(depth, i)
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


class ClosureTracker:
    """Track closure cells to their source code locations."""

    def __init__(self: ClosureTracker) -> None:
        """Initialize the closure tracker."""
        # Maps cell id to (filename, lineno) where the cell was created
        self.cell_metadata = {}
        # Per-frame state to track known functions and last line
        self.frame_states = {}

    def trace_dispatch(
        self: ClosureTracker,
        frame: types.FrameType,
        event: str,
        arg: object | None = None,
    ) -> Callable | None:
        """Intercept trace events to track closure cells."""
        if event == 'call':
            return self.trace_call(frame)
        if event == 'line':
            return self.trace_line(frame, event, arg)
        if event == 'return':
            return self.trace_return(frame, arg)
        return self.trace_dispatch

    def trace_call(self: ClosureTracker, frame: types.FrameType) -> Callable:
        """Initialize state when a function is called."""
        self.frame_states[id(frame)] = {
            'known_func_objs': set(),  # Track function objects by identity
            'last_line': None,
        }
        return self.trace_line

    def trace_line(
        self: ClosureTracker,
        frame: types.FrameType,
        event: str,
        arg: object | None = None,
    ) -> Callable | None:
        """Handle line events to detect new function definitions."""
        _ = event, arg
        state = self.frame_states.get(id(frame))
        if not state:
            return None
        known_func_objs = state['known_func_objs']
        last_line = state['last_line']

        if last_line is not None:
            # Find functions with closures in current locals
            current_func_objs = set()
            for obj in frame.f_locals.values():
                with contextlib.suppress(ReferenceError):
                    if isinstance(obj, types.FunctionType) and obj.__closure__:
                        current_func_objs.add(obj)
            # Identify new functions since the last line
            new_func_objs = current_func_objs - known_func_objs
            for func in new_func_objs:
                # Capture the full stack trace at this point
                stack = traceback.extract_stack(frame)
                traceback_list = [(fs.filename, fs.lineno, fs.name) for fs in stack]
                # Associate the traceback with each closure cell
                for cell in func.__closure__:
                    self.cell_metadata[id(cell)] = traceback_list
            # Update the set of known functions
            state['known_func_objs'] = current_func_objs

        state['last_line'] = frame.f_lineno
        return self.trace_line

    def trace_return(self: ClosureTracker, frame: types.FrameType, arg: object) -> None:
        """Handle return events to catch functions not stored in locals."""
        state = self.frame_states.get(id(frame))
        if not state:
            return
        known_func_objs = state['known_func_objs']
        last_line = state['last_line']

        # Check locals for any new functions defined on the last line
        if last_line is not None:
            current_func_objs = {
                obj
                for obj in frame.f_locals.values()
                if isinstance(obj, types.FunctionType) and obj.__closure__
            }
            new_func_objs = current_func_objs - known_func_objs
            for func in new_func_objs:
                for cell in func.__closure__:
                    self.cell_metadata[id(cell)] = (frame.f_code.co_filename, last_line)
            state['known_func_objs'] = current_func_objs

        # Check return value for a function not previously seen
        if (
            isinstance(arg, types.FunctionType)
            and arg.__closure__
            and arg not in known_func_objs
        ):
            for cell in arg.__closure__:
                self.cell_metadata[id(cell)] = (
                    frame.f_code.co_filename,
                    frame.f_lineno,
                )

        # Clean up frame state
        del self.frame_states[id(frame)]

    def start_tracking(self: ClosureTracker) -> None:
        """Start tracing."""
        sys.settrace(self.trace_dispatch)

    def stop_tracking(self: ClosureTracker) -> None:
        """Stop tracing."""
        sys.settrace(None)
        self.cell_metadata.clear()
        self.frame_states.clear()

    def get_cell_info(self: ClosureTracker, cell: types.CellType) -> str:
        """Retrieve metadata for a given cell."""
        return self.cell_metadata.get(id(cell), 'Unknown')
