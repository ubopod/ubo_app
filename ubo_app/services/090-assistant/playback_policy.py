"""Which one-shot sessions want their audio returned instead of spoken.

A report frame identifies only its session, not the request that asked for it,
so the choice made on the request is remembered here until that session's last
frame arrives.
"""

from __future__ import annotations

_silent_sessions: set[str] = set()


def remember(session_id: str, *, play_locally: bool) -> None:
    """Record a session whose audio must not reach the speaker."""
    if not play_locally:
        _silent_sessions.add(session_id)


def should_play(session_id: str, *, is_last_frame: bool) -> bool:
    """Whether this frame's audio belongs on the device speaker.

    The session is forgotten on its last frame, so a long-running device does not
    accumulate one entry per request that ever asked to stay quiet.
    """
    if session_id not in _silent_sessions:
        return True
    if is_last_frame:
        _silent_sessions.discard(session_id)
    return False
