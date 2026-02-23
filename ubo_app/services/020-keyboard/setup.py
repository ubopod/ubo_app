# ruff: noqa: D103
"""Keyboard service - placeholder for desktop keyboard handling.

Desktop keyboard mappings are handled by the GUI client (`ubo-gui-client`)
which dispatches keypad actions via gRPC. Physical keypad events come from
the `000-keypad` service (GPIO/I2C).

This service's `init_service` is a no-op.
"""

from __future__ import annotations


def init_service() -> list:
    return []
