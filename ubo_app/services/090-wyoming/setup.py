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
    STATUS_ICON_ID,
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

from ubo_app.colors import RUNNING_COLOR, STOPPED_COLOR
from ubo_app.logger import logger
from ubo_app.store.core.action_registry import register_action, unregister_action
from ubo_app.store.core.types import (
    MenuItemData,
    RegisterSettingAppAction,
    SettingsCategory,
    StackPushMenuAction,
    UpdateDynamicMenuAction,
)
from ubo_app.store.core.view_registry import register_path_menu_matcher
from ubo_app.store.input.types import (
    InputFieldDescription,
    InputFieldType,
    WebUIInputDescription,
)
from ubo_app.store.main import store
from ubo_app.store.services.audio import AudioPlaybackDoneEvent, AudioReportSampleEvent
from ubo_app.store.services.notifications import (
    Importance,
    Notification,
    NotificationDisplayType,
    NotificationsAddAction,
)
from ubo_app.store.services.wyoming import (
    WyomingConnectionPolicy,
    WyomingEnginesStatus,
    WyomingSatelliteStatus,
    WyomingSatelliteWakeEvent,
    WyomingSetAllowedPeersAction,
    WyomingSetConnectionPolicyAction,
    WyomingSetEnginesEnabledAction,
    WyomingSetSatelliteEnabledAction,
    WyomingSetZeroconfEnabledAction,
    WyomingState,
)
from ubo_app.store.status_icons.types import StatusIconsRegisterAction
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

    async def reconcile(self, state: WyomingState) -> None:
        """Restart listeners only when their bind, policy, or enablement changes."""
        configuration = (
            state.is_satellite_enabled,
            state.is_engines_enabled,
            state.connection_policy,
            state.allowed_peers,
            state.is_zeroconf_enabled,
        )
        # This autorun observes the whole slice, so it also fires on every
        # satellite and engine status report. Compare before resolving anything
        # to keep those transitions off the Docker daemon.
        if configuration == self._configuration:
            return
        # Recorded only once the listeners are actually up, so a failed attempt
        # is retried by the next reconcile instead of being cached as done.
        self._configuration = None
        await self._stop_servers()

        access = PeerAccess(
            policy=state.connection_policy,
            allowed_peers=state.allowed_peers,
            docker_networks=(
                await resolve_bridge_subnets()
                if state.connection_policy
                == WyomingConnectionPolicy.DOCKER_HOME_ASSISTANT
                else ()
            ),
        )

        if not access.is_configured:
            logger.warning(
                'Wyoming policy %s has no permitted peers; not opening a listener',
                state.connection_policy.value,
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

        if (
            state.connection_policy == WyomingConnectionPolicy.ALLOWLIST
            and state.is_zeroconf_enabled
        ):
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
        'wyoming:connection_policy',
        lambda state: state.wyoming.connection_policy,
    )
    register_persistent_store(
        'wyoming:allowed_peers',
        lambda state: list(state.wyoming.allowed_peers),
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


async def _choose_policy() -> None:
    """Ask for an explicit connection policy instead of exposing all LAN peers."""
    try:
        _, result = await ubo_input(
            prompt='Choose who may connect to Wyoming',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='policy',
                            label='Connection policy',
                            type=InputFieldType.SELECT,
                            options=[
                                policy.value for policy in WyomingConnectionPolicy
                            ],
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if result is None:
        return
    try:
        policy = WyomingConnectionPolicy(result.data.get('policy', ''))
    except ValueError:
        return
    store.dispatch(WyomingSetConnectionPolicyAction(policy=policy))
    if policy != WyomingConnectionPolicy.LOCAL_ONLY:
        _network_warning()


async def _edit_allowed_peers() -> None:
    """Capture an IP/CIDR allowlist through the existing trusted input flow."""
    try:
        _, result = await ubo_input(
            prompt='Enter Home Assistant IP addresses or CIDRs, comma-separated',
            descriptions=[
                WebUIInputDescription(
                    fields=[
                        InputFieldDescription(
                            name='peers',
                            label='Allowed Home Assistant peers',
                            type=InputFieldType.TEXT,
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    except asyncio.CancelledError:
        return
    if result is None:
        return
    value = result.data.get('peers', '')
    peers = [peer.strip() for peer in value.split(',') if peer.strip()]
    store.dispatch(WyomingSetAllowedPeersAction(peers=peers))


def _register_actions() -> list[str]:
    """Register every dynamic-menu action exactly once."""
    action_ids = [
        'wyoming:goto:*',
        'wyoming:toggle-satellite',
        'wyoming:toggle-engines',
        'wyoming:choose-policy',
        'wyoming:edit-allowed-peers',
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
    register_action(
        'wyoming:choose-policy',
        lambda: create_task(_choose_policy()),
        allow_reregister=True,
    )
    register_action(
        'wyoming:edit-allowed-peers',
        lambda: create_task(_edit_allowed_peers()),
        allow_reregister=True,
    )
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


def _menu_items(state: WyomingState) -> tuple[MenuItemData, ...]:
    """Build the Assistant settings menu from desired and effective state."""
    items: list[MenuItemData] = [
        MenuItemData(
            key='wyoming:satellite',
            label=f'Satellite: {"On" if state.is_satellite_enabled else "Off"}',
            icon='󰍬' if state.is_satellite_enabled else '󰍭',
            action_id='wyoming:toggle-satellite',
        ),
        MenuItemData(
            key='wyoming:engines',
            label=f'ASR/TTS/LLM Engines: {"On" if state.is_engines_enabled else "Off"}',
            icon='󰊠' if state.is_engines_enabled else '󰊡',
            action_id='wyoming:toggle-engines',
        ),
        MenuItemData(
            key='wyoming:policy',
            label=f'Connections: {state.connection_policy.value}',
            icon='󰌷',
            action_id='wyoming:choose-policy',
        ),
    ]
    if state.connection_policy == WyomingConnectionPolicy.ALLOWLIST:
        items.append(
            MenuItemData(
                key='wyoming:allowed-peers',
                label=(
                    f'Allowed HA peers: {", ".join(state.allowed_peers)}'
                    if state.allowed_peers
                    else 'Allowed HA peers: not configured'
                ),
                icon='󰒍',
                action_id='wyoming:edit-allowed-peers',
            ),
        )
    if state.connection_policy == WyomingConnectionPolicy.ALLOWLIST:
        items.append(
            MenuItemData(
                key='wyoming:zeroconf',
                label=(
                    'Zeroconf discovery: '
                    f'{"On" if state.is_zeroconf_enabled else "Off"}'
                ),
                icon='󰖟' if state.is_zeroconf_enabled else '󰖠',
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
        store.dispatch(
            StatusIconsRegisterAction(
                id=STATUS_ICON_ID,
                icon='󰍬' if running else '󰍭',
                color=RUNNING_COLOR if running else STOPPED_COLOR,
            ),
        )

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
