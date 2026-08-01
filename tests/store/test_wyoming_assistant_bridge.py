"""Cancellation behavior for the Wyoming-to-assistant frame bridge."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / 'ubo_app' / 'services' / '090-wyoming'
)
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


@pytest.mark.asyncio
async def test_cancelled_request_dispatches_matching_assistant_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disconnects cancel the exact correlated request instead of timing out."""
    import assistant_bridge  # type: ignore[reportMissingImports]
    from assistant_bridge import (  # type: ignore[reportMissingImports]
        AssistantBridge,
        AssistantBridgeCancelledError,
    )

    from ubo_app.store.services.assistant import (
        AssistantCancelRequestAction,
        AssistantCompleteAction,
    )

    dispatched: list[object] = []
    monkeypatch.setattr(assistant_bridge.store, 'dispatch', dispatched.append)
    cancelled = asyncio.Event()
    cancelled.set()
    bridge = AssistantBridge()
    request = bridge.request(
        lambda session_id: AssistantCompleteAction(text='hello', session_id=session_id),
        cancelled=cancelled,
    )

    with pytest.raises(AssistantBridgeCancelledError):
        await anext(request)

    request_action, cancel_action = dispatched
    assert isinstance(request_action, AssistantCompleteAction)
    assert isinstance(cancel_action, AssistantCancelRequestAction)
    assert cancel_action.session_id == request_action.session_id


@pytest.mark.asyncio
async def test_backlogged_response_fails_instead_of_losing_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response the client cannot keep up with must fail, never be truncated.

    Evicting a frame to make room would delete audio from the middle of an
    utterance or text from the middle of an answer while the request still
    finished successfully, so Home Assistant would speak the damage as if whole.
    """
    import assistant_bridge  # type: ignore[reportMissingImports]
    from assistant_bridge import (  # type: ignore[reportMissingImports]
        AssistantBridge,
        AssistantBridgeError,
    )

    from ubo_app.store.services.assistant import (
        REQUEST_PIPELINE_SOURCE_ID,
        AssistanceTextFrame,
        AssistantCompleteAction,
        AssistantHandleReportEvent,
    )

    dispatched: list[AssistantCompleteAction] = []
    monkeypatch.setattr(assistant_bridge.store, 'dispatch', dispatched.append)
    bridge = AssistantBridge()
    request = bridge.request(
        lambda session_id: AssistantCompleteAction(text='hello', session_id=session_id),
    )

    # Start the request so it dispatches and begins waiting on its queue.
    pending_first = asyncio.ensure_future(anext(request))
    await asyncio.sleep(0)
    session_id = dispatched[0].session_id

    # Report far more frames than the queue holds without letting the consumer
    # run, which is exactly what a slow Home Assistant socket produces.
    for index in range(128):
        await bridge._on_report(  # noqa: SLF001
            AssistantHandleReportEvent(
                source_id=REQUEST_PIPELINE_SOURCE_ID,
                data=AssistanceTextFrame(
                    is_last_frame=False,
                    timestamp=0.0,
                    id='report',
                    index=index,
                    session_id=session_id,
                    text=f'chunk-{index}',
                ),
            ),
        )

    assert (await pending_first).text == 'chunk-0'
    with pytest.raises(AssistantBridgeError, match='outpaced'):
        await anext(request)
