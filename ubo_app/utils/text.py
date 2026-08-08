"""Text helpers shared across services."""

from __future__ import annotations

import re


def slugify(name: str) -> str:
    """Reduce a display name to a lowercase, underscore-separated id.

    Underscores (rather than dashes) keep the result usable as a dotenv key.
    Returns an empty string when *name* holds no letters or digits — callers
    must treat that as invalid input rather than minting a blank id.
    """
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
