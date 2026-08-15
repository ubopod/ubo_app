"""Wire the MQTT bridge into the store."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import commands
import ha_commands
from client import (
    bridge_task,
    close_session_tasks,
    enqueue,
    request_announce,
    request_reconnect,
)
from menu import init_menu

from ubo_app.store.main import store
from ubo_app.store.services.mqtt import (
    ALLOW_REMOTE_CONTROL_PERSISTENT_KEY,
    BROKER_PERSISTENT_KEY,
    BUNDLED_CREDENTIALS_REVISION_PERSISTENT_KEY,
    BUNDLED_EXPOSE_TO_LAN_PERSISTENT_KEY,
    IS_ENABLED_PERSISTENT_KEY,
    PUBLISHED_COMPONENTS_PERSISTENT_KEY,
    MqttAnnounceRequestedEvent,
    MqttPublishEvent,
    persist_broker,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.mqtt_registry import (
    register_mqtt_components,
)
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from ubo_app.store.services.mqtt import MqttBrokerConfig, MqttComponent
    from ubo_app.utils.types import Subscriptions


def _handle_publish(event: MqttPublishEvent) -> None:
    enqueue(event)


def _handle_announce_requested(_: MqttAnnounceRequestedEvent) -> None:
    request_announce()


def _watch_connection_settings(_: tuple[bool, MqttBrokerConfig, bool]) -> None:
    """End the live session whenever what it was built from changes.

    Without this, saving a new broker — or switching the bridge off — has no
    effect until the connection happens to fail, which for a healthy broker is
    never. Remote control is in here too: it decides whether the session
    subscribes to command topics, which can only be done at subscribe time.
    """
    request_reconnect()


def _command_components() -> list[MqttComponent]:
    """Offer the inbound command entities.

    Unconditional — the bridge filters commandable entities globally when Home
    Assistant control is off.
    """
    return ha_commands.components()


async def init_service() -> Subscriptions:
    """Start the broker session supervisor and bridge the store to it."""
    # `register_persistent_store` registers an autorun and returns its
    # unsubscribe. Each one joins `Subscriptions` below — otherwise a restart
    # leaves listeners bound to a stopped event loop.
    unregister_persistence = [
        register_persistent_store(
            BROKER_PERSISTENT_KEY,
            lambda state: persist_broker(state.mqtt.broker),
        ),
        register_persistent_store(
            IS_ENABLED_PERSISTENT_KEY,
            lambda state: state.mqtt.is_enabled,
        ),
        register_persistent_store(
            ALLOW_REMOTE_CONTROL_PERSISTENT_KEY,
            lambda state: state.mqtt.allow_remote_control,
        ),
        register_persistent_store(
            BUNDLED_EXPOSE_TO_LAN_PERSISTENT_KEY,
            lambda state: state.mqtt.bundled_expose_to_lan,
        ),
        register_persistent_store(
            BUNDLED_CREDENTIALS_REVISION_PERSISTENT_KEY,
            lambda state: state.mqtt.bundled_credentials_revision,
        ),
        register_persistent_store(
            PUBLISHED_COMPONENTS_PERSISTENT_KEY,
            # The plain dict, not a JSON string: this selector runs on *every*
            # dispatch process-wide, and serializing just so the autorun can
            # compare-and-discard is wasted work. `_parse_published_components`
            # reads either shape back.
            lambda state: state.mqtt.published_components,
        ),
    ]

    unregister_menu = init_menu()
    unregister_components = register_mqtt_components(
        'mqtt_commands',
        _command_components,
    )

    # Subscribed here rather than at import: a module-level `@store.autorun`
    # registers a listener the moment the file is imported.
    connection_settings = store.autorun(
        lambda state: (
            state.mqtt.is_enabled,
            state.mqtt.broker,
            state.mqtt.allow_remote_control,
        ),
    )(_watch_connection_settings)

    end_event = asyncio.Event()
    create_task(bridge_task(end_event))

    return [
        *unregister_persistence,
        end_event.set,
        close_session_tasks,
        connection_settings.unsubscribe,
        commands.SCOPE.aclose,
        unregister_components,
        *unregister_menu,
        store.subscribe_event(MqttPublishEvent, _handle_publish),
        store.subscribe_event(
            MqttAnnounceRequestedEvent,
            _handle_announce_requested,
        ),
    ]
