"""Docker app registry — aggregates all per-app ContainerEntry definitions."""

from __future__ import annotations

from apps._registry import ContainerEntry
from apps.envoy import ENTRY as ENVOY_ENTRY
from apps.hermes import ENTRY as HERMES_ENTRY
from apps.immich import ENTRY as IMMICH_ENTRY
from apps.n8n import ENTRY as N8N_ENTRY
from apps.ngrok import ENTRY as NGROK_ENTRY
from apps.openclaw import ENTRY as OPENCLAW_ENTRY
from apps.pangolin import ENTRY as PANGOLIN_ENTRY
from apps.simple import ENTRIES as SIMPLE_ENTRIES
from apps.twingate import ENTRY as TWINGATE_ENTRY

__all__ = ['IMAGES', 'PREDEFINED_IMAGE_IDS', 'ContainerEntry']

IMAGES: dict[str, ContainerEntry] = {
    entry.id: entry
    for entry in [
        *SIMPLE_ENTRIES,
        NGROK_ENTRY,
        IMMICH_ENTRY,
        N8N_ENTRY,
        OPENCLAW_ENTRY,
        HERMES_ENTRY,
        PANGOLIN_ENTRY,
        TWINGATE_ENTRY,
        ENVOY_ENTRY,
    ]
}

PREDEFINED_IMAGE_IDS = frozenset(IMAGES.keys())
