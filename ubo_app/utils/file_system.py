"""File system utilities for handling file paths and sizes."""

from __future__ import annotations


def human_readable_size(size: float, decimal_places: int = 2) -> str:
    """Convert a size in bytes to a human-readable format."""
    for unit in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if size < 2**10:
            return (
                f'{size} {unit}'
                if unit == 'bytes'
                else f'{size:.{decimal_places}f} {unit}'
            )
        size /= 2.0**10

    return f'{size:.{decimal_places}f} PB'
