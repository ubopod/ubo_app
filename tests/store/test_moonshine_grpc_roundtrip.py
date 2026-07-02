"""gRPC-boundary serialization test for the Moonshine downloaded-models wrapper.

The assistant subprocess subscribes to
``state.assistant.moonshine_downloaded_models_wrapper`` over gRPC. A selector
can't return the bare ``moonshine_downloaded_models`` tuple, because
``_pack_to_any`` rejects container return types
(``TypeError: Containers are not yet supported in the return type of a
selector.``) — the ``_wrapper`` mirror (a message with an ``items`` field) is
what crosses the boundary instead. This guards that the wrapper packs and
round-trips its model ids.

Compares by string (not identity) because integration tests earlier in the full
suite wipe ``sys.modules``; ``rebuild_object`` resolves classes via the registry,
which can be a different generation than the one imported here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ubo_app.rpc.message_to_object import rebuild_object
from ubo_app.rpc.object_to_message import build_message
from ubo_app.store.services.assistant import MoonshineDownloadedModels

if TYPE_CHECKING:
    import betterproto


def _roundtrip(wrapper: MoonshineDownloadedModels) -> MoonshineDownloadedModels:
    message = cast('betterproto.Message', build_message(wrapper))
    return cast('MoonshineDownloadedModels', rebuild_object(message))


def test_downloaded_models_wrapper_survives_roundtrip() -> None:
    """The wrapper round-trips its model ids (the raw tuple can't cross gRPC)."""
    rebuilt = _roundtrip(MoonshineDownloadedModels(items=['tiny', 'base-streaming']))
    assert list(rebuilt.items) == ['tiny', 'base-streaming']


def test_empty_downloaded_models_wrapper_roundtrips_to_empty() -> None:
    """An empty wrapper stays empty (no phantom ids) after a round-trip."""
    rebuilt = _roundtrip(MoonshineDownloadedModels(items=[]))
    assert list(rebuilt.items) == []
