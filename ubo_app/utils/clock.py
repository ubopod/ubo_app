"""Single source of wall-clock truth for reducer-side timestamps.

Reducers must be pure functions of ``(state, action)`` — calling
``datetime.datetime.now`` inside a case makes snapshot/replay behaviour
nondeterministic. Instead, actions that need a timestamp default it via
:func:`default_now` (resolved once when the action is constructed); tests
can monkey-patch this helper for deterministic time.
"""

from __future__ import annotations

import datetime


def default_now() -> float:
    """Return the current UTC wall-clock time as a POSIX timestamp.

    Used as the ``default_factory`` for ``timestamp`` fields on actions
    consumed by ``last_activity_time``-style reducers (chat overlay
    dismiss countdown, display blank timer). Tests can monkey-patch this
    function (e.g. ``monkeypatch.setattr(clock, 'default_now', lambda: 100.0)``)
    to freeze the clock without touching every action constructor.
    """
    return datetime.datetime.now(tz=datetime.UTC).timestamp()
