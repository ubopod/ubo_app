"""Lifecycle, settings UI, persistence, and discovery for Wyoming."""

from __future__ import annotations

import asyncio
import re
import socket
from typing import TYPE_CHECKING

from assistant_bridge import AssistantBridge
from constants import (
    SATELLITES_MENU_ID,
    SECURITY_WARNING_ID,
    WYOMING_ENGINES_LISTEN_PORT,
    WYOMING_MENU_ID,
    WYOMING_SATELLITE_LISTEN_PORT,
)
from docker_networks import resolve_bridge_subnets
from engines import EnginesServer
from redux import AutorunOptions
from satellite import SatelliteServer
from security import PeerAccess
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPopAction,
    StackPushMenuAction,
    StackPushPromptAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import register_path_menu_matcher
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.audio import (
    AudioPlaybackDoneEvent,
    AudioReportRemoteCaptureAction,
    AudioReportSampleEvent,
)
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.wyoming import (
    WyomingAccessPolicy,
    WyomingAccessPolicyKind,
    WyomingAddAccessPolicyAction,
    WyomingEnginesStatus,
    WyomingRemoveAccessPolicyAction,
    WyomingSatelliteStatus,
    WyomingSatelliteWakeEvent,
    WyomingSetEnginesEnabledAction,
    WyomingSetSatelliteEnabledAction,
    WyomingSetZeroconfEnabledAction,
    WyomingState,
    normalize_network,
)
from ubo_app.utils.async_ import create_task
from ubo_app.utils.input import ubo_input
from ubo_app.utils.persistent_store import register_persistent_store

if TYPE_CHECKING:
    from ubo_app.utils.types import Subscriptions


class _ZeroconfRegistry:
    """Own mDNS registration and teardown instead of leaking advertisements."""

    def __init__(self) -> None:
        self._zeroconf: AsyncZeroconf | None = None
        self._services: list[AsyncServiceInfo] = []

    async def start(self, services: tuple[tuple[str, int], ...]) -> None:
        """Advertise active remote listeners on the local IPv4 interface."""
        await self.stop()
        address = _local_ipv4()
        if address is None or not services:
            return
        self._zeroconf = AsyncZeroconf()
        name_prefix = re.sub(r'[^A-Za-z0-9-]', '-', socket.gethostname())
        try:
            for suffix, port in services:
                info = AsyncServiceInfo(
                    '_wyoming._tcp.local.',
                    f'ubo-{name_prefix}-{suffix}._wyoming._tcp.local.',
                    addresses=[socket.inet_aton(address)],
                    port=port,
                )
                await self._zeroconf.async_register_service(info)
                self._services.append(info)
        except Exception:
            logger.exception('Failed to register Wyoming zeroconf service')
            await self.stop()

    async def stop(self) -> None:
        """Remove every registration and close its multicast socket."""
        if self._zeroconf is None:
            return
        for service in self._services:
            try:
                await self._zeroconf.async_unregister_service(service)
            except Exception:  # noqa: BLE001
                logger.warning('Failed to unregister Wyoming zeroconf service')
        self._services.clear()
        await self._zeroconf.async_close()
        self._zeroconf = None


def _local_ipv4() -> str | None:
    """Find the source IP used for LAN traffic without emitting a packet."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1', 1))
            address = sock.getsockname()[0]
    except OSError:
        return None
    return address if address and not address.startswith('127.') else None


class WyomingRuntime:
    """Converge sockets and discovery on the immutable Wyoming configuration."""

    def __init__(self) -> None:
        """Initialize network servers and their shared assistant-output bridge."""
        self.bridge = AssistantBridge()
        self._satellite: SatelliteServer | None = None
        self._engines: EnginesServer | None = None
        self._zeroconf = _ZeroconfRegistry()
        self._configuration: tuple[object, ...] | None = None
        # Starting a listener dispatches a status action, and this runtime's
        # autorun observes the slice that status lives in — so a reconcile
        # re-triggers itself before it has recorded what it applied. Without
        # serializing, the two passes overlap on the same fixed ports and the
        # loser dies with EADDRINUSE, leaving the runtime with no listeners
        # while the winner's socket stays bound and answering.
        self._lock = asyncio.Lock()

    async def reconcile(self, state: WyomingState) -> None:
        """Restart listeners only when their bind, policy, or enablement changes."""
        configuration = (
            state.is_satellite_enabled,
            state.is_engines_enabled,
            state.access_policies,
            state.is_zeroconf_enabled,
        )
        async with self._lock:
            await self._reconcile(state, configuration)

    async def _reconcile(
        self,
        state: WyomingState,
        configuration: tuple[object, ...],
    ) -> None:
        # This autorun observes the whole slice, so it also fires on every
        # satellite and engine status report. Compare before resolving anything
        # to keep those transitions off the Docker daemon. Inside the lock, so a
        # pass that queued behind the one which applied this very configuration
        # short-circuits instead of pointlessly restarting the listeners.
        if configuration == self._configuration:
            return
        # Recorded only once the listeners are actually up, so a failed attempt
        # is retried by the next reconcile instead of being cached as done.
        self._configuration = None
        await self._stop_servers()

        access = PeerAccess(policies=state.access_policies)
        if access.wants_docker_networks:
            access = PeerAccess(
                policies=state.access_policies,
                docker_networks=await resolve_bridge_subnets(),
            )

        if not access.is_configured:
            logger.warning(
                'Wyoming policies resolve to no permitted peers; '
                'not opening a listener',
            )
            return

        try:
            if state.is_satellite_enabled:
                self._satellite = SatelliteServer(
                    host=access.host,
                    port=WYOMING_SATELLITE_LISTEN_PORT,
                    access=access,
                )
                await self._satellite.start()
            if state.is_engines_enabled:
                self._engines = EnginesServer(
                    host=access.host,
                    port=WYOMING_ENGINES_LISTEN_PORT,
                    access=access,
                    bridge=self.bridge,
                )
                await self._engines.start()
        except OSError:
            logger.exception('Unable to bind Wyoming listener')
            await self._stop_servers()
            return

        if state.access_policies and state.is_zeroconf_enabled:
            await self._zeroconf.start(
                tuple(
                    service
                    for enabled, service in (
                        (
                            state.is_satellite_enabled,
                            ('satellite', WYOMING_SATELLITE_LISTEN_PORT),
                        ),
                        (
                            state.is_engines_enabled,
                            ('engines', WYOMING_ENGINES_LISTEN_PORT),
                        ),
                    )
                    if enabled
                ),
            )

        self._configuration = configuration

    async def _stop_servers(self) -> None:
        await self._zeroconf.stop()
        if self._satellite is not None:
            await self._satellite.stop()
            self._satellite = None
        if self._engines is not None:
            await self._engines.stop()
            self._engines = None

    async def microphone(self, event: AudioReportSampleEvent) -> None:
        """Forward only the physical device microphone to the satellite."""
        if not event.audio_source and self._satellite is not None:
            await self._satellite.enqueue_microphone(event.sample_speech_recognition)

    async def playback_done(self, event: AudioPlaybackDoneEvent) -> None:
        """Release a satellite's ``played`` event after actual speaker drain."""
        if self._satellite is not None:
            await self._satellite.playback_done(event)

    async def wake(self, event: WyomingSatelliteWakeEvent) -> None:
        """Start a Home Assistant pipeline run from a local wake-word detection."""
        if self._satellite is not None:
            await self._satellite.wake(event.phrase, event.detector)

    async def close(self) -> None:
        """Close network state during service teardown."""
        self._configuration = None
        # The microphone icon belongs to the audio service now, so it outlives
        # this one — release its colour rather than leaving it reading as live.
        store.dispatch(AudioReportRemoteCaptureAction(is_active=False))
        await self._stop_servers()


def _register_persistence() -> None:
    """Persist user intent, never transient connection state."""
    register_persistent_store(
        'wyoming:is_satellite_enabled',
        lambda state: state.wyoming.is_satellite_enabled,
    )
    register_persistent_store(
        'wyoming:is_engines_enabled',
        lambda state: state.wyoming.is_engines_enabled,
    )
    register_persistent_store(
        'wyoming:access_policies',
        lambda state: [
            {'kind': policy.kind.value, 'value': policy.value}
            for policy in state.wyoming.access_policies
        ],
    )
    register_persistent_store(
        'wyoming:is_zeroconf_enabled',
        lambda state: state.wyoming.is_zeroconf_enabled,
    )


def _network_warning() -> None:
    """Keep microphone and cloud-provider risks visible when leaving loopback."""
    store.dispatch(
        NotificationsAddAction(
            notification=Notification(
                id=SECURITY_WARNING_ID,
                title='Home Assistant Voice Access',
                content=(
                    'Wyoming has no authentication. Only the selected Docker '
                    'bridge or explicitly allowed Home Assistant addresses can connect.'
                ),
                importance=Importance.HIGH,
                display_type=NotificationDisplayType.STICKY,
                icon='󰀪',
            ),
        ),
    )


# Labels for the source picker; matched back by value when the form returns.
_DOCKER_OPTION = 'Docker bridge'
_NETWORK_OPTION = 'IP address or CIDR'


async def _add_policy() -> None:
    """Permit one more source, rather than replacing what is already permitted.

    Sources combine, so adding the Docker bridge does not withdraw an address
    that was allowed before it.
    """
    try:
        _, result = await ubo_input(
            prompt='Choose a source to permit',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='kind',
                            label='Source',
                            type=InputFieldType.SELECT,
                            options=[_DOCKER_OPTION, _NETWORK_OPTION],
                            required=True,
                        ),
                        InputFieldDescription(
                            name='value',
                            label='IP address or CIDR',
                            description=(
                                'Only for an address source; ignored for Docker.'
                            ),
                            type=InputFieldType.TEXT,
                            required=False,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if result is None:
        return

    if result.data.get('kind') == _DOCKER_OPTION:
        store.dispatch(
            WyomingAddAccessPolicyAction(kind=WyomingAccessPolicyKind.DOCKER),
        )
        _network_warning()
        return

    value = normalize_network(result.data.get('value', ''))
    if value is None:
        store.dispatch(
            NotificationsAddAction(
                notification=Notification(
                    title='Wyoming',
                    content=(
                        'Enter an IP address or CIDR, e.g. 192.168.1.20 or '
                        '192.168.1.0/24. Host names are not accepted.'
                    ),
                    importance=Importance.LOW,
                ),
            ),
        )
        return
    store.dispatch(
        WyomingAddAccessPolicyAction(
            kind=WyomingAccessPolicyKind.NETWORK,
            value=value,
        ),
    )
    _network_warning()


def _policy_label(policy: WyomingAccessPolicy) -> str:
    """Render a policy short enough for the LCD."""
    if policy.kind == WyomingAccessPolicyKind.DOCKER:
        return 'Docker bridge'
    return policy.value


def _register_actions() -> list[str]:
    """Register every dynamic-menu action exactly once."""
    action_ids = [
        'wyoming:goto:*',
        'wyoming:toggle-satellite',
        'wyoming:toggle-engines',
        'wyoming:add-policy',
        'wyoming:remove-policy:*',
        'wyoming:confirm-remove-policy:*',
        'wyoming:cancel',
        'wyoming:toggle-zeroconf',
    ]

    def _goto(action_id: str) -> None:
        # The dynamic-menu id is carried verbatim after the prefix.
        store.dispatch(
            StackPushMenuAction(menu_key=action_id.removeprefix('wyoming:goto:')),
        )

    @store.with_state(lambda state: state.wyoming)
    def _toggle_satellite(state: WyomingState) -> None:
        store.dispatch(
            WyomingSetSatelliteEnabledAction(enabled=not state.is_satellite_enabled),
        )

    @store.with_state(lambda state: state.wyoming)
    def _toggle_engines(state: WyomingState) -> None:
        store.dispatch(
            WyomingSetEnginesEnabledAction(enabled=not state.is_engines_enabled),
        )

    @store.with_state(lambda state: state.wyoming)
    def _toggle_zeroconf(state: WyomingState) -> None:
        store.dispatch(
            WyomingSetZeroconfEnabledAction(enabled=not state.is_zeroconf_enabled),
        )

    register_action('wyoming:goto:*', _goto, allow_reregister=True)
    register_action(
        'wyoming:toggle-satellite',
        _toggle_satellite,
        allow_reregister=True,
    )
    register_action(
        'wyoming:toggle-engines',
        _toggle_engines,
        allow_reregister=True,
    )
    def _remove_policy(action_id: str) -> None:
        kind, _, value = action_id.removeprefix(
            'wyoming:remove-policy:',
        ).partition(':')
        label = _policy_label(
            WyomingAccessPolicy(kind=WyomingAccessPolicyKind(kind), value=value),
        )
        store.dispatch(
            StackPushPromptAction(
                title='Remove Policy',
                prompt=f'Stop permitting {label}?',
                icon='\U000f0a7a',
                items=(
                    MenuItemData(
                        key='yes',
                        label='Remove',
                        icon='\U000f0a7a',
                        action_id=f'wyoming:confirm-remove-policy:{kind}:{value}',
                    ),
                    MenuItemData(
                        key='cancel',
                        label='Cancel',
                        icon='\U000f0156',
                        action_id='wyoming:cancel',
                    ),
                ),
            ),
        )

    def _confirm_remove_policy(action_id: str) -> None:
        kind, _, value = action_id.removeprefix(
            'wyoming:confirm-remove-policy:',
        ).partition(':')
        store.dispatch(
            StackPopAction(),
            WyomingRemoveAccessPolicyAction(
                kind=WyomingAccessPolicyKind(kind),
                value=value,
            ),
        )

    def _cancel() -> None:
        store.dispatch(StackPopAction())

    register_action(
        'wyoming:add-policy',
        lambda: create_task(_add_policy()),
        allow_reregister=True,
    )
    register_action('wyoming:remove-policy:*', _remove_policy, allow_reregister=True)
    register_action(
        'wyoming:confirm-remove-policy:*',
        _confirm_remove_policy,
        allow_reregister=True,
    )
    register_action('wyoming:cancel', _cancel, allow_reregister=True)
    register_action(
        'wyoming:toggle-zeroconf',
        _toggle_zeroconf,
        allow_reregister=True,
    )
    return action_ids


def _dispatch_satellites_menu() -> None:
    """Publish the container listing every supported satellite protocol.

    Static, so it is dispatched once at startup rather than from the state
    autorun. A second protocol becomes one more row here plus its own menu.
    """
    store.dispatch(
        UpdateDynamicMenuAction(
            menu_id=SATELLITES_MENU_ID,
            title='Satellites',
            heading='Satellites',
            sub_heading='Voice satellite protocols.',
            items=(
                MenuItemData(
                    key='wyoming',
                    label='Wyoming',
                    icon='󰟐',
                    action_id=f'wyoming:goto:{WYOMING_MENU_ID}',
                ),
            ),
            placeholder='',
        ),
    )


def _settings_path_matcher(path: tuple[str, ...]) -> str | None:
    """Resolve a settings path to one of this service's dynamic menus.

    The entry point is now a container, so the first level is the satellite list
    and anything deeper was pushed by explicit ``menu_key`` — for which the
    dynamic-menu id always equals the trailing path segment.
    """
    settings_depth = 4
    if len(path) >= settings_depth and path[3] == 'wyoming:':
        if len(path) == settings_depth:
            return SATELLITES_MENU_ID
        return path[-1]
    return None


# Checkbox glyphs for on/off rows — marked means enabled, blank means disabled.
# The same pair the WiFi hotspot row uses, so a toggle reads the same everywhere.
_CHECKED = '\U000f0c52'
_UNCHECKED = '\U000f0131'


def _toggle(
    *,
    key: str,
    label: str,
    enabled: bool,
    action_id: str,
) -> MenuItemData:
    """Build an on/off row whose checkbox carries the state.

    The label stays bare — no ``: On``/``: Off`` suffix — because the checkbox
    already says it and the LCD is narrow enough that the suffix pushes real
    labels off the edge.
    """
    return MenuItemData(
        key=key,
        label=label,
        icon=_CHECKED if enabled else _UNCHECKED,
        action_id=action_id,
    )


def _menu_items(state: WyomingState) -> tuple[MenuItemData, ...]:
    """Build the Assistant settings menu from desired and effective state."""
    items: list[MenuItemData] = [
        _toggle(
            key='wyoming:satellite',
            label='Satellite',
            enabled=state.is_satellite_enabled,
            action_id='wyoming:toggle-satellite',
        ),
        _toggle(
            key='wyoming:engines',
            label='STT/TTS/LLM',
            enabled=state.is_engines_enabled,
            action_id='wyoming:toggle-engines',
        ),
    ]
    # One row per permitted source, so each can be withdrawn on its own. With
    # none listed the listener is loopback-only, which is what the empty state
    # says rather than leaving the section blank.
    items.extend(
        MenuItemData(
            key=f'wyoming:policy:{policy.kind.value}:{policy.value}',
            label=_policy_label(policy),
            icon=(
                '\U000f0868'
                if policy.kind == WyomingAccessPolicyKind.DOCKER
                else '\U000f048d'
            ),
            action_id=(
                f'wyoming:remove-policy:{policy.kind.value}:{policy.value}'
            ),
        )
        for policy in state.access_policies
    )
    if not state.access_policies:
        items.append(
            MenuItemData(
                key='wyoming:no-policy',
                label='Local only',
                icon='\U000f0335',
                action_id='wyoming:add-policy',
            ),
        )
    items.append(
        MenuItemData(
            key='wyoming:add-policy',
            label='Add Policy',
            icon='\U000f0415',
            action_id='wyoming:add-policy',
        ),
    )
    if state.access_policies:
        items.append(
            _toggle(
                key='wyoming:zeroconf',
                label='Discovery',
                enabled=state.is_zeroconf_enabled,
                action_id='wyoming:toggle-zeroconf',
            ),
        )
    return tuple(items)


async def init_service() -> Subscriptions:
    """Register menu state, persistence, and safely bounded network listeners."""
    runtime = WyomingRuntime()
    _register_persistence()
    action_ids = _register_actions()
    unregister_path_matcher = register_path_menu_matcher(
        'wyoming:settings',
        _settings_path_matcher,
    )
    _dispatch_satellites_menu()

    @store.autorun(lambda state: state.wyoming)
    async def _reconcile(state: WyomingState) -> None:
        await runtime.reconcile(state)

    @store.autorun(lambda state: state.wyoming)
    def _update_menu(state: WyomingState) -> None:
        store.dispatch(
            UpdateDynamicMenuAction(
                menu_id=WYOMING_MENU_ID,
                title='Wyoming',
                heading=f'Satellite: {state.satellite_status.value}',
                sub_heading=(
                    f'Satellite {WYOMING_SATELLITE_LISTEN_PORT} · '
                    f'Engines {WYOMING_ENGINES_LISTEN_PORT}'
                ),
                items=_menu_items(state),
            ),
        )

    @store.autorun(
        lambda state: (state.wyoming.satellite_status, state.wyoming.engines_status),
        options=AutorunOptions(default_value=None),
    )
    def _status_icon(
        statuses: tuple[WyomingSatelliteStatus, WyomingEnginesStatus] | None,
    ) -> None:
        if statuses is None:
            return
        satellite_status, engines_status = statuses
        running = (
            satellite_status.value not in ('stopped', 'paused')
            or engines_status.value != 'stopped'
        )
        # Colour the audio service's microphone icon rather than registering a
        # second one: two icons with the same glyph competed for the four status
        # slots, and the loser (the real microphone indicator, lowest priority)
        # was silently dropped.
        store.dispatch(AudioReportRemoteCaptureAction(is_active=running))

    store.dispatch(
        RegisterSettingAppAction(
            category=SettingsCategory.ASSISTANT,
            priority=5,
            label='Satellites',
            icon='󰤈',
        ),
    )

    def _cleanup_actions() -> None:
        for action_id in action_ids:
            unregister_action(action_id)

    return [
        *runtime.bridge.subscriptions(),
        store.subscribe_event(AudioReportSampleEvent, runtime.microphone),
        store.subscribe_event(AudioPlaybackDoneEvent, runtime.playback_done),
        store.subscribe_event(WyomingSatelliteWakeEvent, runtime.wake),
        _reconcile.unsubscribe,
        _update_menu.unsubscribe,
        _status_icon.unsubscribe,
        unregister_path_matcher,
        _cleanup_actions,
        runtime.close,
    ]
