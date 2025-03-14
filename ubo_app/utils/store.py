# ruff: noqa: D100, D101, D102, D103, D104, D107
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, cast

from ubo_app.store.core.types import ReportReplayingDoneAction

if TYPE_CHECKING:
    from pathlib import Path

    from ubo_app.store.main import UboStore


async def replay_actions(store: UboStore, path: Path) -> None:
    with path.open('r') as file:
        data = json.load(file)

    for item in data:
        store.dispatch(cast('Any', store.load_object(item)))
        await asyncio.sleep(0.5)
    await asyncio.sleep(1.5)
    store.dispatch(ReportReplayingDoneAction())
