"""Tests for StoreService logging helpers."""

from __future__ import annotations

from ubo_app.rpc.store_service import _should_log_dispatched_action


class AssistantReportAction:
    """Action name that should be omitted from generic gRPC dispatch logs."""


class AssistantStartListeningAction:
    """Representative action that should stay visible in gRPC dispatch logs."""


def test_assistant_report_actions_are_not_logged_generically() -> None:
    """Assistant report actions are high-volume and get dedicated logs."""
    assert not _should_log_dispatched_action(AssistantReportAction())


def test_non_report_actions_are_logged_generically() -> None:
    """Lower-volume actions remain visible in generic gRPC dispatch logs."""
    assert _should_log_dispatched_action(AssistantStartListeningAction())
