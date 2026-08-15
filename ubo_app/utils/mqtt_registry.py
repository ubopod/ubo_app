"""Where services declare the Home Assistant entities they contribute.

Deliberately *not* in `store/services/mqtt.py`. That module is the MQTT store
schema — serializable types the proto generator turns into gRPC messages — and
this is runtime machinery: a dict of callables, executed by the bridge, that
could never cross a wire. Keeping the two apart is also what stops a provider
type leaking into the generated schema with its one meaningful field dropped.

It lives outside any service because services cannot import each other, and a
contribution is a *provider callable*, not a fixed list, because the set is
live: the sensors service gains and loses entities on every re-scan, and the
infrared service one button per device you teach it. The provider is called
only when the bridge (re)announces, never on the publish hot path.

Changing what a provider *would* return has no effect on its own — dispatch
`MqttRequestAnnounceAction` to ask the bridge to rebuild and republish.

Lifecycle
---------
`register_mqtt_components` returns the unregister, and it belongs in the
contributing service's `init_service()` subscriptions. A service that does not
return it leaks a provider that closes over a module the service loader has
already evicted, and the bridge will keep announcing entities for a service
that is no longer running. Re-registering the same `source_id` raises rather
than replacing, because a service that reaches that point has already leaked
its previous registration.

Threading
---------
Registration happens on the *contributing* service's thread; collection happens
on the MQTT service's event loop, whenever it announces. There is no lock, and
none is needed: the only mutations are whole-key assignment and deletion, and
`get_mqtt_components` iterates a snapshot (`list(_registry.items())`), so a
service starting or stopping mid-announce cannot corrupt the walk. The worst
case is an entity set that is one announce out of date, which the next
`MqttRequestAnnounceAction` corrects.

What that costs a provider: it is called **on another service's event loop**,
so it must be cheap, must not block, and must not touch hardware. It must not
dispatch either — it runs inside the announce path. Read state with
`store.with_state` and return. A provider that raises is logged and skipped, so
one misbehaving service cannot stop the pod being announced, but it will
silently lose its own entities until it stops raising.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ubo_app.logger import logger
from ubo_app.store.services.mqtt import MqttRequestAnnounceAction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ubo_app.store.services.mqtt import MqttComponent


# Module-level singleton registry, source id -> provider (insertion order is
# preserved for determinism, so the generated discovery payload is stable).
#
# A plain dict rather than a wrapper type: nothing here needs one, and a
# `NamedTuple` of (source_id, provider) is exactly the shape that used to get
# swept into the generated schema.
_registry: dict[str, Callable[[], Sequence[MqttComponent]]] = {}


def _request_announce() -> None:
    """Ask the bridge to re-announce because the contributor set changed.

    Without it, stopping a service leaves its entities on the Home Assistant
    dashboard until something unrelated happens to trigger an announce.

    `store` is imported here rather than at module scope: this module is loaded
    while the store is still being assembled, so a top-level import would be a
    cycle.
    """
    from ubo_app.store.main import store

    store.dispatch(MqttRequestAnnounceAction())


def register_mqtt_components(
    source_id: str,
    provider: Callable[[], Sequence[MqttComponent]],
) -> Callable[[], None]:
    """Register a source of Home Assistant entities.

    Args:
        source_id: Stable identifier for the contributing service, e.g.
            ``sensors``. Used only for bookkeeping and unregistration — it does
            **not** namespace the component ids, so each contributor is
            responsible for keeping its own ``component_id``s unique.
        provider: Returns the current entity set. Called on every announce.

    Returns:
        A callable that unregisters this contribution.

    Raises:
        ValueError: If ``source_id`` is already registered. A service that
            re-registers has leaked its previous registration — the unregister
            returned here belongs in `init_service`'s subscriptions.

    """
    if source_id in _registry:
        msg = f"MQTT components for '{source_id}' are already registered"
        raise ValueError(msg)

    _registry[source_id] = provider
    logger.debug('Registered MQTT components: %s', source_id)
    _request_announce()

    def unregister() -> None:
        unregister_mqtt_components(source_id)

    return unregister


def unregister_mqtt_components(source_id: str) -> bool:
    """Unregister a contribution.

    Returns:
        True if the source was found and removed, False otherwise.

    """
    if source_id in _registry:
        del _registry[source_id]
        logger.debug('Unregistered MQTT components: %s', source_id)
        _request_announce()
        return True
    return False


def clear_all_mqtt_components() -> None:
    """Clear every contribution.

    Primarily useful for testing.
    """
    _registry.clear()
    logger.debug('Cleared all MQTT components')


def get_mqtt_components() -> list[MqttComponent]:
    """Return every contributed entity, in registration order.

    A provider that raises is logged and skipped — one misbehaving service must
    not stop the rest of the pod from being announced.
    """
    components: list[MqttComponent] = []
    for source_id, provider in list(_registry.items()):
        try:
            components.extend(provider())
        except Exception:
            logger.exception(
                'Failed to collect MQTT components',
                extra={'source_id': source_id},
            )
    return components
