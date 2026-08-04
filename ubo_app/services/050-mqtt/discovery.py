"""Build the Home Assistant device-level discovery payload.

Home Assistant learns about the pod from a single retained message on
``homeassistant/device/<id>/config`` declaring every entity at once. Getting a
key wrong here means the entity silently never appears, so this module does no
broker I/O and is pinned against a golden payload in
`tests/store/test_mqtt_discovery.py`. Its one impurity is `get_pod_id`, which
reads the pod-id file for the device name.

Entities arrive as :class:`MqttComponent`s — Home Assistant's vocabulary, not
any service's — from the shared contribution registry.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from topics import availability_topic, channel_topic

from ubo_app._version import __version__
from ubo_app.utils.pod_id import get_pod_id

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ubo_app.store.services.mqtt import MqttComponent

_NO_REMOVALS: Mapping[str, str] = MappingProxyType({})


# `MqttComponent` attribute -> Home Assistant's abbreviated discovery key.
# Home Assistant accepts the full names too, but the abbreviations are what the
# rest of the ecosystem emits, and a wrong key fails silently — so the mapping
# is a single reviewable table rather than scattered through the renderer.
_CHANNEL_KEYS: tuple[tuple[str, str], ...] = (
    ('state_channel', 'stat_t'),
    ('command_channel', 'cmd_t'),
)
_SCALAR_KEYS: tuple[tuple[str, str], ...] = (
    ('value_template', 'val_tpl'),
    ('command_template', 'cmd_tpl'),
    ('expire_after', 'exp_aft'),
    ('device_class', 'dev_cla'),
    ('unit_of_measurement', 'unit_of_meas'),
    ('state_class', 'stat_cla'),
    ('suggested_display_precision', 'sug_dsp_prc'),
    ('payload_press', 'pl_prs'),
    # Home Assistant does not abbreviate these four.
    ('min_value', 'min'),
    ('max_value', 'max'),
    ('step', 'step'),
    ('mode', 'mode'),
    ('retain', 'ret'),
    ('qos', 'qos'),
)
_SEQUENCE_KEYS: tuple[tuple[str, str], ...] = (
    ('event_types', 'evt_typ'),
    ('options', 'ops'),
)


def _render(serial: str, component: MqttComponent) -> dict[str, Any]:
    """Render one entity using Home Assistant's abbreviated discovery keys.

    Optional metadata is omitted rather than sent as null — Home Assistant
    treats an explicit null differently from an absent key.
    """
    rendered: dict[str, Any] = {
        'p': component.platform,
        'unique_id': f'ubo_{serial}_{component.component_id}',
        'name': component.name,
    }
    for attribute, key in _CHANNEL_KEYS:
        value = getattr(component, attribute)
        if value is not None:
            rendered[key] = channel_topic(serial, value)
    for attribute, key in _SCALAR_KEYS:
        value = getattr(component, attribute)
        if value is not None:
            rendered[key] = value
    for attribute, key in _SEQUENCE_KEYS:
        value = getattr(component, attribute)
        if value:
            rendered[key] = list(value)
    return rendered


def build_discovery_payload(
    serial: str,
    components: Sequence[MqttComponent],
    *,
    removed_components: Mapping[str, str] = _NO_REMOVALS,
) -> dict[str, Any]:
    """Describe every entity the pod exposes, in one device-level payload.

    Home Assistant removes an entity when its component key is republished with
    an otherwise-empty config, so `removed_components` — a mapping of component
    id to its platform — is how a sensor that has been unplugged disappears from
    the dashboard instead of lingering as "unavailable" forever.
    """
    rendered = {
        component.component_id: _render(serial, component) for component in components
    }

    # A config carrying nothing but the platform tells Home Assistant to forget
    # the component. The platform is *not* optional here — the discovery docs
    # are explicit that `p` is still required on a removal — which is why the
    # caller has to remember what platform it published, not just the id.
    # `setdefault` so a component that is both live and stale-listed stays live.
    for component_id, platform in removed_components.items():
        rendered.setdefault(component_id, {'p': platform})

    return {
        'dev': {
            'ids': [f'ubo_{serial}'],
            'name': get_pod_id(with_default=True),
            'mf': 'Ubo',
            'mdl': 'Ubo Pod',
            'sw': __version__,
        },
        'o': {'name': 'ubo-app', 'sw': __version__},
        'avty_t': availability_topic(serial),
        'cmps': rendered,
    }


def component_platforms(components: Sequence[MqttComponent]) -> dict[str, str]:
    """Map each entity's component key to its platform.

    The bridge keeps the last one of these so it can diff against the next
    announce; the platform is carried because a removal payload has to repeat it.
    """
    return {component.component_id: component.platform for component in components}
