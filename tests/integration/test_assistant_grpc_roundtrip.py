"""Full gRPC round-trip for the assistant one-shot pipeline.

Boots the real core gRPC server + the ``bin/ubo-assistant`` subprocess (on the
real filesystem, with real secrets/models), dispatches ``AssistantSynthesizeAction``
over the wire via the StoreService stub, and asserts the subprocess streams an
audio report back over gRPC. This exercises the whole path
(client → gRPC → core reducer → event → subprocess → pipeline → report → gRPC)
that the subprocess- and store-boundary suites cover only in isolation.

Live test: needs network/creds and spawns a real subprocess, so it is opt-in via
``UBO_RUN_GRPC_E2E=1`` and never runs in default CI. Uses Piper (local) so the
round-trip itself needs no cloud provider.

    UBO_RUN_GRPC_E2E=1 uv run pytest \
        tests/integration/test_assistant_grpc_roundtrip.py -v
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from immutable import Immutable
    from redux_pytest.fixtures import WaitFor

    from tests.fixtures import AppContext, LoadServices
    from tests.fixtures.dispatch import Dispatcher

pytestmark = pytest.mark.skipif(
    not os.environ.get('UBO_RUN_GRPC_E2E'),
    reason='set UBO_RUN_GRPC_E2E=1 to run the live gRPC assistant round-trip '
    '(needs real creds + network + the assistant subprocess)',
)


async def _dispatch_action_over_grpc(
    dispatcher: Dispatcher,
    action: Immutable,
) -> None:
    """Serialize *action* and send it through the StoreService gRPC stub."""
    import ubo_bindings.ubo.v1
    from betterproto.casing import snake_case
    from ubo_bindings.store.v1 import DispatchActionRequest

    from ubo_app.rpc.object_to_message import build_message

    stub = dispatcher.stub
    assert stub is not None, 'dispatcher fixture has no gRPC stub'
    # ``Action`` is a oneof; set the member matching the action's snake_case name.
    # setattr keeps the field dynamic without casting the proto to Any.
    wrapped = ubo_bindings.ubo.v1.Action()
    setattr(wrapped, snake_case(type(action).__name__), build_message(action))
    await stub.dispatch_action(DispatchActionRequest(action=wrapped))


async def test_assistant_grpc_synthesize_round_trip(
    app_context: AppContext,
    load_services: LoadServices,
    dispatcher: Dispatcher,
    wait_for: WaitFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatch synthesize over gRPC; assert the subprocess streams audio back."""
    from uuid import uuid4

    import platformdirs
    from tenacity import wait_fixed

    from ubo_app.store.main import store
    from ubo_app.store.services.assistant import (
        AssistanceAudioFrame,
        AssistantHandleReportEvent,
        AssistantSynthesizeAction,
        AssistantTTSName,
    )

    # The test harness isolates the core's DATA_PATH to /tmp (tests/.env), which
    # has no Piper voice. Point only the spawned subprocess at the real user data
    # dir so it can load the (read-only) voice; the core keeps its isolation, so
    # the user's persisted state.json is untouched.
    monkeypatch.setattr(
        'ubo_app.service_thread.DATA_PATH',
        platformdirs.user_data_path(appname='ubo'),
    )

    app_context.set_app()
    # Only the assistant service is needed: the test asserts on the report event
    # the subprocess streams back, not on audio playback (which would need an
    # audio device). Service ids are registered ids, not directory names.
    await load_services(['assistant'], timeout=60, run_async=True)

    audio_reports: list[AssistantHandleReportEvent] = []
    unsubscribe = store.subscribe_event(
        AssistantHandleReportEvent,
        audio_reports.append,
    )

    async def _keep_dispatching() -> None:
        # The subprocess registers its gRPC run-pipeline subscription a moment
        # after the service reports started, so the first dispatch can race ahead
        # of it. Re-dispatch (fresh session each time) until a report arrives.
        while True:
            await _dispatch_action_over_grpc(
                dispatcher,
                AssistantSynthesizeAction(
                    text='the quick brown fox',
                    session_id=uuid4().hex,
                    tts_provider=AssistantTTSName.PIPER,
                ),
            )
            await asyncio.sleep(3)

    dispatch_task = asyncio.ensure_future(_keep_dispatching())

    try:

        @wait_for(run_async=True, timeout=120, wait=wait_fixed(2))
        def _audio_arrived() -> None:
            assert any(
                isinstance(report.data, AssistanceAudioFrame) and report.data.audio
                for report in audio_reports
            ), 'no audio report received from the assistant subprocess'

        await _audio_arrived()
    finally:
        dispatch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await dispatch_task
        unsubscribe()
