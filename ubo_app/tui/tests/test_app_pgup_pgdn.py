"""Tests for the UboTUI page-up / page-down navigation actions."""

from __future__ import annotations

from typing import Any

import pytest

ITEM_COUNT = 9
LAST_INDEX = ITEM_COUNT - 1


@pytest.mark.asyncio
async def test_page_down_jumps_by_page_step() -> None:
    """Page-down should advance the selection index by PAGE_STEP."""
    from ubo_tui.app import UboTUI

    app = UboTUI()
    app._current_view = "menu"  # noqa: SLF001
    app._item_count = ITEM_COUNT  # noqa: SLF001
    app._selected_index = 0  # noqa: SLF001

    # Stub out _update_view_selection — it queries widgets that aren't
    # mounted in this minimal harness.
    app._update_view_selection = lambda: None  # type: ignore[method-assign]  # noqa: SLF001

    app.action_page_down()
    assert app._selected_index == UboTUI.PAGE_STEP  # noqa: SLF001


@pytest.mark.asyncio
async def test_page_down_clamps_to_last_index() -> None:
    """Page-down past the end should clamp to item_count - 1."""
    from ubo_tui.app import UboTUI

    app = UboTUI()
    app._current_view = "menu"  # noqa: SLF001
    app._item_count = ITEM_COUNT  # noqa: SLF001
    app._selected_index = UboTUI.PAGE_STEP  # already past page step  # noqa: SLF001
    app._update_view_selection = lambda: None  # type: ignore[method-assign]  # noqa: SLF001

    app.action_page_down()
    assert app._selected_index == LAST_INDEX  # noqa: SLF001


@pytest.mark.asyncio
async def test_page_up_jumps_back_by_page_step() -> None:
    """Page-up should retreat by PAGE_STEP."""
    from ubo_tui.app import UboTUI

    app = UboTUI()
    app._current_view = "menu"  # noqa: SLF001
    app._item_count = ITEM_COUNT  # noqa: SLF001
    app._selected_index = LAST_INDEX  # noqa: SLF001
    app._update_view_selection = lambda: None  # type: ignore[method-assign]  # noqa: SLF001

    app.action_page_up()
    assert app._selected_index == LAST_INDEX - UboTUI.PAGE_STEP  # noqa: SLF001


@pytest.mark.asyncio
async def test_page_up_clamps_to_zero() -> None:
    """Page-up at the start should not go negative."""
    from ubo_tui.app import UboTUI

    app = UboTUI()
    app._current_view = "menu"  # noqa: SLF001
    app._item_count = ITEM_COUNT  # noqa: SLF001
    app._selected_index = 2  # noqa: SLF001
    app._update_view_selection = lambda: None  # type: ignore[method-assign]  # noqa: SLF001

    app.action_page_up()
    assert app._selected_index == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_page_navigation_no_op_in_non_navigable_views() -> None:
    """Page-up/down should be a no-op when the current view isn't navigable."""
    from ubo_tui.app import UboTUI

    app = UboTUI()
    app._current_view = "instruction"  # not in navigable_views  # noqa: SLF001
    app._item_count = 0  # noqa: SLF001
    app._selected_index = 0  # noqa: SLF001
    calls: list[str] = []
    app._update_view_selection = (  # type: ignore[method-assign]  # noqa: SLF001
        lambda: calls.append("call")
    )

    app.action_page_down()
    app.action_page_up()
    assert app._selected_index == 0  # noqa: SLF001
    assert calls == []


@pytest.mark.asyncio
async def test_page_navigation_calls_update_view_selection() -> None:
    """A successful page-down should trigger _update_view_selection()."""
    from ubo_tui.app import UboTUI

    app = UboTUI()
    app._current_view = "menu"  # noqa: SLF001
    app._item_count = ITEM_COUNT  # noqa: SLF001
    app._selected_index = 0  # noqa: SLF001
    calls: list[str] = []
    app._update_view_selection = (  # type: ignore[method-assign]  # noqa: SLF001
        lambda: calls.append("update")
    )

    app.action_page_down()
    assert calls == ["update"]


@pytest.mark.asyncio
async def test_page_down_no_op_when_already_at_end() -> None:
    """Repeated page-down at the last index should not call update."""
    from ubo_tui.app import UboTUI

    app = UboTUI()
    app._current_view = "menu"  # noqa: SLF001
    app._item_count = ITEM_COUNT  # noqa: SLF001
    app._selected_index = LAST_INDEX  # noqa: SLF001
    calls: list[Any] = []
    app._update_view_selection = (  # type: ignore[method-assign]  # noqa: SLF001
        lambda: calls.append("update")
    )

    app.action_page_down()
    assert app._selected_index == LAST_INDEX  # noqa: SLF001
    assert calls == []
