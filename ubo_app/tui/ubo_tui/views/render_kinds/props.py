"""Helpers to extract typed values from RenderViewData.props."""

from __future__ import annotations

from typing import Any


def _props_map(view_data: Any) -> dict[str, Any]:
    """Return the prop entry map from a RenderViewData."""
    props = getattr(view_data, "props", None)
    if props is None:
        return {}
    items = getattr(props, "items", None)
    if items is None:
        return {}
    if isinstance(items, dict):
        return items
    # betterproto map fields are sometimes exposed via .items() iteration only.
    try:
        return dict(items)
    except TypeError:
        return {}


def _basic_value(entry: Any) -> Any:
    if entry is None:
        return None
    return getattr(entry, "basic_type", None)


def _list_items(entry: Any) -> list[Any]:
    if entry is None:
        return []
    list_value = getattr(entry, "list", None)
    if list_value is None:
        return []
    items = getattr(list_value, "items", None)
    return list(items) if items else []


def prop_string(view_data: Any, key: str, default: str = "") -> str:
    entry = _props_map(view_data).get(key)
    basic = _basic_value(entry)
    if basic is None:
        return default
    value = getattr(basic, "string", None)
    return value if isinstance(value, str) and value else default


def prop_number(view_data: Any, key: str, default: float = 0.0) -> float:
    entry = _props_map(view_data).get(key)
    basic = _basic_value(entry)
    if basic is None:
        return default
    int_val = getattr(basic, "int64", None)
    if isinstance(int_val, int) and int_val:
        return float(int_val)
    float_val = getattr(basic, "float", None)
    if isinstance(float_val, (int, float)) and float_val:
        return float(float_val)
    return default


def prop_bytes(view_data: Any, key: str) -> bytes | None:
    entry = _props_map(view_data).get(key)
    basic = _basic_value(entry)
    if basic is None:
        return None
    raw = getattr(basic, "bytes", None)
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return bytes(raw)
    return None


def prop_string_list(view_data: Any, key: str) -> list[str]:
    entry = _props_map(view_data).get(key)
    items = _list_items(entry)
    out: list[str] = []
    for item in items:
        value = getattr(item, "string", None)
        if isinstance(value, str) and value:
            out.append(value)
    return out
