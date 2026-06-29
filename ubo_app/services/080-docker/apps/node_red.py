"""Node-RED Docker composition — the add-on-contract proof.

Node-RED is a self-contained Compose stack that joins the shared `ubo_net`
bus and integrates with the rest of the ecosystem purely by service name:
the bundled MQTT broker as `mosquitto:1883` and Home Assistant as
`http://homeassistant:8123`. It owns no devices, so it never contends with
ZHA for the Zigbee coordinator. Starting/stopping/removing it never disturbs
HA, the broker, or `ubo_net`.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from apps._registry import COMPOSITIONS_PATH, UBO_NET, ContainerEntry
from ubo_app.constants import CONFIG_PATH
from ubo_app.logger import logger

if TYPE_CHECKING:
    from pathlib import Path

NODE_RED_COMPOSITION_ID = 'node_red'
NODE_RED_LABEL = 'Node-RED'
NODE_RED_ICON = '󰚀'
NODE_RED_IMAGE = 'nodered/node-red:latest'

# Persistent host directory for Node-RED flows/state, kept OUTSIDE the
# composition directory so `docker compose down -v` / uninstall can't destroy
# the user's flows (Hermes/HA data-path precedent).
NODE_RED_DATA_PATH = CONFIG_PATH / 'node-red'


def _write_node_red_compose(composition_path: Path) -> None:
    data_path = NODE_RED_DATA_PATH / 'data'
    # The nodered/node-red image runs as a fixed uid 1000 and writes to /data.
    # `prepare_node_red` creates the bind-mounted host dir as the core process's
    # user, so pin the container to that same uid:gid — otherwise Node-RED can't
    # write its settings/flows and crash-loops with EACCES. (HA runs as root and
    # Mosquitto self-chowns its volume, so only Node-RED needs this.)
    user = f'{os.getuid()}:{os.getgid()}'
    compose_content = (
        'services:\n'
        '  node-red:\n'
        f'    image: {NODE_RED_IMAGE}\n'
        '    container_name: node-red\n'
        '    restart: unless-stopped\n'
        f'    user: "{user}"\n'
        '    volumes:\n'
        f'      - {data_path}:/data\n'
        # Default to loopback — Node-RED has no auth and allows code execution.
        # `supports_lan_toggle=True` lets the port-binding helper strip the
        # 127.0.0.1 host IP (→ 0.0.0.0) only when the user explicitly opts into
        # LAN exposure; rendering loopback in the source keeps the file
        # safe-by-default even if read or brought up without the rewrite.
        '    ports:\n'
        '      - "127.0.0.1:1880:1880"\n'
        '    networks:\n'
        f'      - {UBO_NET}\n'
        'networks:\n'
        f'  {UBO_NET}:\n'
        '    external: true\n'
    )
    (composition_path / 'docker-compose.yml').write_text(compose_content)


def _write_node_red_metadata(composition_path: Path) -> None:
    metadata = {
        'label': NODE_RED_LABEL,
        'icon': NODE_RED_ICON,
        'instructions': (
            'Node-RED is installed and running.\n\n'
            'Open port 1880 on this device in a browser to edit flows. '
            'On the shared network it reaches the bundled broker at '
            'mosquitto:1883 and Home Assistant at http://homeassistant:8123.'
        ),
        'compose_id': NODE_RED_COMPOSITION_ID,
    }
    (composition_path / 'metadata.json').write_text(json.dumps(metadata))


async def prepare_node_red() -> bool:
    """Render Node-RED's compose file and create its persistent data dir."""
    try:
        logger.info('Preparing Node-RED composition')
        composition_path = COMPOSITIONS_PATH / NODE_RED_COMPOSITION_ID
        composition_path.mkdir(exist_ok=True, parents=True)
        (NODE_RED_DATA_PATH / 'data').mkdir(exist_ok=True, parents=True)
        _write_node_red_compose(composition_path)
        _write_node_red_metadata(composition_path)
    except Exception:
        logger.exception('Failed to prepare Node-RED')
        return False
    else:
        return True


ENTRY = ContainerEntry(
    id=NODE_RED_COMPOSITION_ID,
    label=NODE_RED_LABEL,
    icon=NODE_RED_ICON,
    path=NODE_RED_IMAGE,
    registry='docker.io',
    prepare=prepare_node_red,
    is_composition=True,
    category='Home Automation',
    requires_mqtt=True,
    # Node-RED's editor has no auth by default and allows arbitrary code
    # execution, so default its published port to loopback; the user opts into
    # LAN exposure via the existing per-app toggle.
    supports_lan_toggle=True,
)
