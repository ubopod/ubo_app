"""Bindable-action catalog and default voice commands.

The built-in voice commands are expressed as data: each maps example phrases to
one or more *bindable-action keys*. The concrete actions behind those keys are
registered into the shared bindable-actions registry by
:func:`register_default_bindable_actions`, so the defaults and any custom
commands created from the Web UI resolve through the same catalog.

This lives in the service (not the store layer) because the factories construct
concrete service actions. The persisted command list is loaded — or seeded with
:data:`DEFAULT_COMMANDS` on first run — by :func:`load_or_seed_commands`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ubo_app.store.core.bindable_actions import register_bindable_action
from ubo_app.store.core.types import (
    ExecuteMenuActionAction,
    MenuChooseByIndexAction,
    MenuGoBackAction,
    MenuGoHomeAction,
    MenuScrollAction,
    MenuScrollDirection,
)
from ubo_app.store.services.audio import AudioChangeVolumeAction, AudioDevice
from ubo_app.store.services.infrared import (
    InfraredRegisterDeviceAction,
    InfraredSendCodeAction,
)
from ubo_app.store.services.rgb_ring import RgbRingRainbowAction, RgbRingSetAllAction
from ubo_app.store.services.speech_recognition import (
    SpeechRecognitionIntent,
    SpeechRecognitionSetAssistantEnabledAction,
    SpeechRecognitionTriggerModeAction,
    WakeMode,
)
from ubo_app.utils.persistent_store import read_from_persistent_store

if TYPE_CHECKING:
    from collections.abc import Callable

    from ubo_app.store.core.bindable_actions import BindableActionContext
    from ubo_app.store.main import UboAction

# Persistent-store key holding the user's voice command list.
COMMANDS_PERSISTENT_KEY = 'speech_recognition:commands'
# Persistent-store key holding the ids of the defaults already offered to this
# device. See :func:`load_or_seed_commands`.
SEEDED_IDS_PERSISTENT_KEY = 'speech_recognition:seeded_default_ids'

# --- Bindable-action keys backing the default commands ----------------------
# Registered by the assistant service: assistant:toggle/start/stop/stop-talking.
# Registered by the infrared service (literal strings shared with that service):
INFRARED_RECEIVE_ON = 'infrared:receive-on'
INFRARED_RECEIVE_OFF = 'infrared:receive-off'
# Registered by the localization service (literal strings shared with it):
LOCALIZATION_SPEAK_TIME = 'localization:speak-time'
LOCALIZATION_SPEAK_DATE = 'localization:speak-date'
LOCALIZATION_SPEAK_WEATHER = 'localization:speak-weather'
# Registered here by register_default_bindable_actions():
SPEECH_ASSISTANT_ON = 'speech:assistant-on'
SPEECH_ASSISTANT_OFF = 'speech:assistant-off'
# Per-mode wake actions — let an Infrared remote key (bound to one of these via
# the wake-phrase editor) trigger an assistant mode. Keyed by WakeMode below.
SPEECH_WAKE_INTENTS = 'speech:wake-intents'
SPEECH_WAKE_QUICK_CHAT = 'speech:wake-quick-chat'
SPEECH_WAKE_CONVERSATION = 'speech:wake-conversation'
SPEECH_WAKE_SILENCE = 'speech:wake-silence'
SPEECH_WAKE_HOME_ASSISTANT = 'speech:wake-home-assistant'
MODE_BINDABLE_KEY: dict[WakeMode, str] = {
    WakeMode.INTENTS: SPEECH_WAKE_INTENTS,
    WakeMode.QUICK_CHAT: SPEECH_WAKE_QUICK_CHAT,
    WakeMode.CONVERSATION: SPEECH_WAKE_CONVERSATION,
    WakeMode.STOP_TALKING: SPEECH_WAKE_SILENCE,
    WakeMode.HOME_ASSISTANT: SPEECH_WAKE_HOME_ASSISTANT,
}
# Labels for the per-mode wake actions (shown in the Infrared "Add Keys" Action
# dropdown and the voice-command Action dropdown).
_MODE_BINDABLE_LABEL: dict[WakeMode, str] = {
    WakeMode.INTENTS: 'Wake: Shortcut',
    WakeMode.QUICK_CHAT: 'Wake: Short Chat',
    WakeMode.CONVERSATION: 'Wake: Conversation',
    WakeMode.STOP_TALKING: 'Wake: Silence',
    WakeMode.HOME_ASSISTANT: 'Wake: Home Assistant',
}
SPEECH_WIFI_CAMERA = 'speech:wifi-camera'
SPEECH_WIFI_WEB = 'speech:wifi-web'
SPEECH_LIGHT_STRIP = 'speech:light-strip'
RGB_OFF = 'rgb:off'
RGB_WHITE = 'rgb:white'
RGB_RED = 'rgb:red'
RGB_GREEN = 'rgb:green'
RGB_BLUE = 'rgb:blue'
RGB_RAINBOW = 'rgb:rainbow'
AUDIO_VOLUME_UP = 'audio:volume-up'
AUDIO_VOLUME_DOWN = 'audio:volume-down'
MENU_CHOOSE_1 = 'menu:choose-1'
MENU_CHOOSE_2 = 'menu:choose-2'
MENU_CHOOSE_3 = 'menu:choose-3'
MENU_BACK = 'menu:back'
MENU_HOME = 'menu:home'
MENU_SCROLL_UP = 'menu:scroll-up'
MENU_SCROLL_DOWN = 'menu:scroll-down'


# Run the real add-connection flow (030-wifi), forced to one input method, rather
# than just flashing its final "creating" status with none of the steps before it.
_WIFI_CAMERA_ACTION = ExecuteMenuActionAction(action_id='wifi:add-connection:camera')
_WIFI_WEB_ACTION = ExecuteMenuActionAction(action_id='wifi:add-connection:web')


def _const(action: UboAction) -> Callable[[BindableActionContext], UboAction]:
    """Return a context-ignoring bindable-action factory for *action*."""
    return lambda _ctx: action


def _trigger_mode(mode: WakeMode) -> Callable[[BindableActionContext], UboAction]:
    """Bindable factory: fire an assistant wake *mode* from a bound trigger.

    Used by Infrared remote keys bound to a mode via the wake-phrase editor; the
    device name flows through as the trigger phrase for the assistant source.

    Note: this path deliberately ignores the mode's ``enabled_wake_modes`` switch.
    Unlike audio wake words (which the engines manager stops feeding when the mode
    is switched off), an explicit IR binding is treated as an intentional override —
    it always fires the mode. Keep this in sync with ``reducer._apply_wake_mode``.
    """
    return lambda ctx: SpeechRecognitionTriggerModeAction(
        mode=mode,
        phrase=ctx.device_name,
        detector='infrared',
    )


def register_default_bindable_actions() -> None:
    """Register the bindable actions backing the default voice commands.

    Idempotent (``allow_reregister=True``) so it survives service reloads. The
    assistant listening actions and the infrared receive/send actions are
    registered by their own services.
    """
    catalog: list[tuple[str, str, UboAction]] = [
        (
            SPEECH_ASSISTANT_ON,
            'Assistant: Turn On',
            SpeechRecognitionSetAssistantEnabledAction(enabled=True),
        ),
        (
            SPEECH_ASSISTANT_OFF,
            'Assistant: Turn Off',
            SpeechRecognitionSetAssistantEnabledAction(enabled=False),
        ),
        (SPEECH_WIFI_CAMERA, 'WiFi: Setup via Camera', _WIFI_CAMERA_ACTION),
        (SPEECH_WIFI_WEB, 'WiFi: Setup via Web', _WIFI_WEB_ACTION),
        (
            SPEECH_LIGHT_STRIP,
            'Light Strip: Toggle',
            InfraredSendCodeAction(protocol='nec', scancode='0x40'),
        ),
        (RGB_OFF, 'Lights: Off', RgbRingSetAllAction(color=(0, 0, 0))),
        (RGB_WHITE, 'Lights: White', RgbRingSetAllAction(color=(255, 255, 255))),
        (RGB_RED, 'Lights: Red', RgbRingSetAllAction(color=(255, 0, 0))),
        (RGB_GREEN, 'Lights: Green', RgbRingSetAllAction(color=(0, 255, 0))),
        (RGB_BLUE, 'Lights: Blue', RgbRingSetAllAction(color=(0, 0, 255))),
        (
            RGB_RAINBOW,
            'Lights: Rainbow',
            RgbRingRainbowAction(rounds=0, wait=2500),
        ),
        (
            AUDIO_VOLUME_UP,
            'Volume: Up',
            AudioChangeVolumeAction(amount=0.1, device=AudioDevice.OUTPUT),
        ),
        (
            AUDIO_VOLUME_DOWN,
            'Volume: Down',
            AudioChangeVolumeAction(amount=-0.1, device=AudioDevice.OUTPUT),
        ),
        (MENU_CHOOSE_1, 'Menu: Select Item 1', MenuChooseByIndexAction(index=0)),
        (MENU_CHOOSE_2, 'Menu: Select Item 2', MenuChooseByIndexAction(index=1)),
        (MENU_CHOOSE_3, 'Menu: Select Item 3', MenuChooseByIndexAction(index=2)),
        (MENU_BACK, 'Menu: Back', MenuGoBackAction()),
        (MENU_HOME, 'Menu: Home', MenuGoHomeAction()),
        (
            MENU_SCROLL_UP,
            'Menu: Scroll Up',
            MenuScrollAction(direction=MenuScrollDirection.UP),
        ),
        (
            MENU_SCROLL_DOWN,
            'Menu: Scroll Down',
            MenuScrollAction(direction=MenuScrollDirection.DOWN),
        ),
    ]
    for key, label, action in catalog:
        register_bindable_action(key, label, _const(action), allow_reregister=True)

    # Per-mode wake actions (context-aware — carry the bound device's name as the
    # trigger phrase), so an Infrared remote key can start a mode.
    for mode, key in MODE_BINDABLE_KEY.items():
        register_bindable_action(
            key,
            _MODE_BINDABLE_LABEL[mode],
            _trigger_mode(mode),
            allow_reregister=True,
        )


def register_shortcut_actions() -> None:
    """Register one-utterance shortcut actions for the command picker.

    These collapse multi-step navigation into a single spoken command. They are
    only added to the bindable-actions registry (so they appear in the Add/Edit
    command form) and are NOT seeded as default commands. Two shapes:

    - a direct store action (``InfraredRegisterDeviceAction``); and
    - a flow-opener that triggers an existing menu-action handler via
      ``ExecuteMenuActionAction`` (no ``menu_key``, so no menu frame is pushed).
      ``docker:import_composition`` is owned by the docker service; if it is
      disabled the id simply won't resolve (``execute_action`` is a no-op).
    """
    catalog: list[tuple[str, str, UboAction]] = [
        (
            'infrared:register-device',
            'Infrared: Register Remote Key',
            InfraredRegisterDeviceAction(),
        ),
        (
            'flow:add-voice-command',
            'Add Voice Command',
            ExecuteMenuActionAction(action_id='speech-recognition:add-command'),
        ),
        (
            'flow:add-application',
            'Add Application',
            ExecuteMenuActionAction(action_id='docker:import_composition'),
        ),
    ]
    for key, label, action in catalog:
        register_bindable_action(key, label, _const(action), allow_reregister=True)


# The built-in commands, re-expressed as editable data. Stable ``default:*``
# ids keep snapshot output deterministic. (``default:button-three`` correctly
# selects item index 2 — the legacy hardcoded mapping used index 1, a bug.)
DEFAULT_COMMANDS: list[SpeechRecognitionIntent] = [
    SpeechRecognitionIntent(
        id='default:assistant-on',
        label='Turn on Assistant',
        phrases=['Turn on Assistant'],
        action_keys=[SPEECH_ASSISTANT_ON],
    ),
    SpeechRecognitionIntent(
        id='default:assistant-off',
        label='Turn off Assistant',
        phrases=['Turn off Assistant'],
        action_keys=[SPEECH_ASSISTANT_OFF],
    ),
    SpeechRecognitionIntent(
        id='default:wifi-camera',
        label='WiFi Setup via Camera',
        phrases=[
            'Create WiFi Connection with Camera',
            'Create WiFi Connection with QR Code',
            'Create WiFi Connection using Camera',
            'Create WiFi Connection using QR Code',
        ],
        action_keys=[SPEECH_WIFI_CAMERA],
    ),
    SpeechRecognitionIntent(
        id='default:wifi-web',
        label='WiFi Setup via Web',
        phrases=[
            'Create WiFi Connection with Web Dashboard',
            'Create WiFi Connection with Web',
            'Create WiFi Connection with Web UI',
            'Create WiFi Connection using Web Dashboard',
            'Create WiFi Connection using Web UI',
            'Create WiFi Connection using Web',
        ],
        action_keys=[SPEECH_WIFI_WEB],
    ),
    SpeechRecognitionIntent(
        id='default:light-strip-toggle',
        label='Toggle Light Strip',
        phrases=['Turn on light strip', 'Turn off light strip'],
        action_keys=[SPEECH_LIGHT_STRIP],
    ),
    SpeechRecognitionIntent(
        id='default:lights-on',
        label='Turn on Lights',
        phrases=['Turn on Lights'],
        action_keys=[RGB_WHITE],
    ),
    SpeechRecognitionIntent(
        id='default:lights-off',
        label='Turn off Lights',
        phrases=['Turn off Lights'],
        action_keys=[RGB_OFF],
    ),
    SpeechRecognitionIntent(
        id='default:lights-red',
        label='Turn Lights Red',
        phrases=['Turn Lights Red'],
        action_keys=[RGB_RED],
    ),
    SpeechRecognitionIntent(
        id='default:lights-green',
        label='Turn Lights Green',
        phrases=['Turn Lights Green'],
        action_keys=[RGB_GREEN],
    ),
    SpeechRecognitionIntent(
        id='default:lights-blue',
        label='Turn Lights Blue',
        phrases=['Turn Lights Blue'],
        action_keys=[RGB_BLUE],
    ),
    SpeechRecognitionIntent(
        id='default:lights-white',
        label='Turn Lights White',
        phrases=['Turn Lights White'],
        action_keys=[RGB_WHITE],
    ),
    SpeechRecognitionIntent(
        id='default:lights-rainbow',
        label='Turn Lights Rainbow',
        phrases=['Turn Lights Rainbow'],
        action_keys=[RGB_RAINBOW],
    ),
    SpeechRecognitionIntent(
        id='default:volume-up',
        label='Turn Volume Up',
        phrases=['Turn Volume Up'],
        action_keys=[AUDIO_VOLUME_UP],
    ),
    SpeechRecognitionIntent(
        id='default:volume-down',
        label='Turn Volume Down',
        phrases=['Turn Volume Down'],
        action_keys=[AUDIO_VOLUME_DOWN],
    ),
    SpeechRecognitionIntent(
        id='default:button-one',
        label='Activate Button One',
        phrases=['Activate Button One'],
        action_keys=[MENU_CHOOSE_1],
    ),
    SpeechRecognitionIntent(
        id='default:button-two',
        label='Activate Button Two',
        phrases=['Activate Button Two'],
        action_keys=[MENU_CHOOSE_2],
    ),
    SpeechRecognitionIntent(
        id='default:button-three',
        label='Activate Button Three',
        phrases=['Activate Button Three'],
        action_keys=[MENU_CHOOSE_3],
    ),
    SpeechRecognitionIntent(
        id='default:go-back',
        label='Go Back',
        phrases=['Activate Back Button', 'Go Back'],
        action_keys=[MENU_BACK],
    ),
    SpeechRecognitionIntent(
        id='default:go-home',
        label='Go Home',
        phrases=['Activate Home Button', 'Go Home'],
        action_keys=[MENU_HOME],
    ),
    SpeechRecognitionIntent(
        id='default:scroll-up',
        label='Scroll Up',
        phrases=['Activate Up Button', 'Scroll Up'],
        action_keys=[MENU_SCROLL_UP],
    ),
    SpeechRecognitionIntent(
        id='default:scroll-down',
        label='Scroll Down',
        phrases=['Activate Down Button', 'Scroll Down'],
        action_keys=[MENU_SCROLL_DOWN],
    ),
    SpeechRecognitionIntent(
        id='default:ir-receive-on',
        label='Enable IR Receiver',
        phrases=[
            'Enable Receive Keys',
            'Turn on Receive Keys',
            'Start Receiving IR',
            'Enable IR Receiver',
        ],
        action_keys=[INFRARED_RECEIVE_ON],
    ),
    SpeechRecognitionIntent(
        id='default:ir-receive-off',
        label='Disable IR Receiver',
        phrases=[
            'Disable Receive Keys',
            'Turn off Receive Keys',
            'Stop Receiving IR',
            'Disable IR Receiver',
        ],
        action_keys=[INFRARED_RECEIVE_OFF],
    ),
    SpeechRecognitionIntent(
        id='default:speak-time',
        label='Say the Time',
        phrases=[
            'What time is it (right now)',
            '[Whats, What is] the time',
            'Tell me the time',
        ],
        action_keys=[LOCALIZATION_SPEAK_TIME],
    ),
    SpeechRecognitionIntent(
        id='default:speak-date',
        label='Say the Date',
        phrases=[
            'What day is it (today)',
            '[Whats, What is] the date (today)',
            '[Whats, What is] todays date',
            'Tell me the date',
        ],
        action_keys=[LOCALIZATION_SPEAK_DATE],
    ),
    SpeechRecognitionIntent(
        id='default:speak-weather',
        label='Say the Weather',
        phrases=[
            '[Whats, What is] the weather (like) (today)',
            '[Hows, How is] the weather (today)',
            'Tell me the weather',
        ],
        action_keys=[LOCALIZATION_SPEAK_WEATHER],
    ),
]

# The defaults that shipped before seeded-id tracking existed. On a device that
# already has a persisted command list but no seeded-ids key, these are treated
# as "already offered" — so a default the user deleted back then stays deleted,
# while genuinely new defaults still arrive.
_PRE_TRACKING_DEFAULT_IDS = frozenset(
    {
        'default:assistant-on',
        'default:assistant-off',
        'default:wifi-camera',
        'default:wifi-web',
        'default:light-strip-toggle',
        'default:lights-on',
        'default:lights-off',
        'default:lights-red',
        'default:lights-green',
        'default:lights-blue',
        'default:lights-white',
        'default:lights-rainbow',
        'default:volume-up',
        'default:volume-down',
        'default:button-one',
        'default:button-two',
        'default:button-three',
        'default:go-back',
        'default:go-home',
        'default:scroll-up',
        'default:scroll-down',
        'default:ir-receive-on',
        'default:ir-receive-off',
    },
)


def parse_persisted_commands(value: object) -> list[SpeechRecognitionIntent]:
    """Deserialize the persisted JSON command list into intents."""
    raw = json.loads(value) if isinstance(value, str) else value
    if not isinstance(raw, list):
        return []
    return [
        SpeechRecognitionIntent(
            id=str(item['id']),
            label=str(item['label']),
            phrases=[str(phrase) for phrase in item['phrases']],
            action_keys=[str(key) for key in item['action_keys']],
        )
        for item in raw
    ]


def parse_seeded_ids(value: object) -> tuple[str, ...]:
    """Deserialize the persisted list of already-seeded default command ids."""
    raw = json.loads(value) if isinstance(value, str) else value
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw)


def load_or_seed_commands() -> tuple[list[SpeechRecognitionIntent], tuple[str, ...]]:
    """Load persisted commands, adding any default the device hasn't been offered.

    Returns the command list and the ids of every default now accounted for.

    Seeding by "is the key absent?" alone would mean a device that upgrades never
    receives defaults added by a later release. Merging every missing default on
    each boot would instead resurrect the ones the user deliberately deleted. So
    we track which defaults this device has *been offered*, and only ever add the
    ones it hasn't seen:

    - No stored commands (fresh install) -> seed all defaults.
    - Stored commands, no seeded-ids key (upgrade from before this tracking) ->
      treat the pre-tracking defaults as offered, append only newer defaults.
    - Both stored -> append only defaults in neither the seeded set nor the list.
    """
    loaded = read_from_persistent_store(
        COMMANDS_PERSISTENT_KEY,
        mapper=parse_persisted_commands,
    )
    all_default_ids = tuple(command.id for command in DEFAULT_COMMANDS)

    if loaded is None:
        return list(DEFAULT_COMMANDS), all_default_ids

    seeded = read_from_persistent_store(
        SEEDED_IDS_PERSISTENT_KEY,
        mapper=parse_seeded_ids,
        default=None,
    )
    already_offered = (
        set(_PRE_TRACKING_DEFAULT_IDS) if seeded is None else set(seeded)
    )
    present = {command.id for command in loaded}

    commands = [
        *loaded,
        *(
            command
            for command in DEFAULT_COMMANDS
            if command.id not in already_offered and command.id not in present
        ),
    ]
    return commands, tuple(already_offered | set(all_default_ids))
