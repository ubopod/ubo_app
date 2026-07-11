"""LVGL-based GUI client for Ubo App.

Phase 1: this Python package owns the gRPC connection and translates the core's
ViewData/StatusBarData into calls on the C renderer (libubo_lvgl) via CFFI.
"""
