"""Simple Docker apps that need no prepare function or custom menu actions."""

from __future__ import annotations

from apps._registry import ContainerEntry
from ubo_app.constants import DEBUG_DOCKER

ENTRIES: list[ContainerEntry] = [
    ContainerEntry(
        id='home_bridge',
        label='Home Bridge',
        icon='󰘘',
        path='homebridge/homebridge:latest',
        registry='docker.io',
        category='Home Automation',
    ),
    ContainerEntry(
        id='portainer',
        label='Portainer',
        icon='',
        path='portainer/portainer-ce:latest',
        registry='docker.io',
        volumes=['/var/run/docker.sock:/var/run/docker.sock'],
        category='Container Management',
    ),
    ContainerEntry(
        id='pi_hole',
        label='Pi-hole',
        icon='󰇖',
        hostname='pi.hole',
        note='Password: admin',
        path='pihole/pihole:latest',
        ports={
            '53/tcp': 53,
            '53/udp': 53,
            '80/tcp': 80,
            '443/tcp': 443,
        },
        dns=['127.0.0.1', '1.1.1.1'],
        registry='docker.io',
        category='Networking',
    ),
    ContainerEntry(
        id='ollama',
        label='Ollama',
        icon='󰳆',
        path='ollama/ollama:latest',
        registry='docker.io',
        ports={'11434/tcp': 11434},
        category='AI Engines',
        # Ollama's inference API has no authentication; default to loopback.
        supports_lan_toggle=True,
    ),
    ContainerEntry(
        id='open_webui',
        label='Open WebUI',
        icon='󰾔',
        path='open-webui/open-webui:main',
        registry='ghcr.io',
        dependencies=['ollama'],
        ports={'8080/tcp': 8080},
        hosts={'host.docker.internal': 'host-gateway'},
        category='AI Engines',
    ),
    *(
        [
            ContainerEntry(
                id='alpine',
                label='Alpine',
                icon='',
                path='alpine:latest',
                registry='docker.io',
                category='Other',
            ),
        ]
        if DEBUG_DOCKER
        else []
    ),
]
