"""Unit tests for custom/built-in voice commands in speech-recognition.

Covers the pure command data + reducer logic:
- ``DEFAULT_COMMANDS`` seed (count, the fixed ``button-three`` mapping).
- ``parse_persisted_commands`` / ``load_or_seed_commands`` (absent-vs-empty
  seeding — the subtle bit).
- the bindable-action catalog registration (resolution + idempotency).
- add / update / remove command reducer behaviour.
- intent detection emitting ``SpeechRecognitionBoundActionTriggeredEvent``.

The reducer and ``commands`` module live in a hyphenated service directory, so
they are loaded by file path (mirroring ``test_speech_recognition_wake_words``).
Action classes are read back from the reducer module's namespace so that they
match the generation the reducer matches against, even if an earlier test in the
session reloaded ``ubo_app.store.services.speech_recognition``.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ubo_app.store.core.bindable_actions import BindableActionContext

if TYPE_CHECKING:
    from redux import CompleteReducerResult

    from ubo_app.store.services.speech_recognition import SpeechRecognitionState

SERVICE_PATH = (
    Path(__file__).resolve().parents[2]
    / 'ubo_app'
    / 'services'
    / '090-speech-recognition'
)

_CTX = BindableActionContext(protocol='', scancode='', device_name='test')


def _tv_intent(speech: SimpleNamespace) -> object:
    """Build a stand-alone intent with two bound actions, for detection tests."""
    return speech.SpeechRecognitionIntent(
        id='c',
        label='TV',
        phrases=['turn on tv'],
        action_keys=['infrared:send:nec:0x1', 'rgb:red'],
    )


def _patch_store(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    """Point the persistent store at *path* (which may not exist)."""
    monkeypatch.setattr(
        'ubo_app.utils.persistent_store.PERSISTENT_STORE_PATH',
        path,
    )
    monkeypatch.setattr(
        'ubo_app.constants.PERSISTENT_STORE_PATH',
        path,
        raising=False,
    )


@pytest.fixture
def speech(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load the ``commands`` module and the reducer from the service dir."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    commands_module = importlib.reload(importlib.import_module('commands'))

    # Resolve the bindable-actions registry from the *same* module generation
    # that ``commands`` registers into. ``app_context``-based tests can evict
    # ``ubo_app.store.core.bindable_actions`` from ``sys.modules``; a top-level
    # import here would then read a stale, empty registry (see module docstring).
    bindable_actions = commands_module.register_bindable_action.__globals__
    bindable_actions['clear_all_bindable_actions']()

    spec = importlib.util.spec_from_file_location(
        'speech_recognition_commands_reducer',
        SERVICE_PATH / 'reducer.py',
    )
    assert spec is not None
    assert spec.loader is not None
    reducer_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = reducer_module
    spec.loader.exec_module(reducer_module)

    return SimpleNamespace(
        commands=commands_module,
        get_bindable_action=bindable_actions['get_bindable_action'],
        get_bindable_actions=bindable_actions['get_bindable_actions'],
        reducer=reducer_module.reducer,
        InitAction=reducer_module.reducer.__globals__['InitAction'],
        SpeechRecognitionState=reducer_module.SpeechRecognitionState,
        SpeechRecognitionStatus=reducer_module.SpeechRecognitionStatus,
        SpeechRecognitionIntent=reducer_module.SpeechRecognitionIntent,
        AddCommandAction=reducer_module.SpeechRecognitionAddCommandAction,
        UpdateCommandAction=reducer_module.SpeechRecognitionUpdateCommandAction,
        RemoveCommandAction=reducer_module.SpeechRecognitionRemoveCommandAction,
        ReportIntentDetectionAction=(
            reducer_module.SpeechRecognitionReportIntentDetectionAction
        ),
        IntentTimeoutAction=(
            reducer_module.SpeechRecognitionReportIntentTimeoutAction
        ),
        RunCommandAction=reducer_module.SpeechRecognitionRunCommandAction,
        SetAssistantListeningAction=(
            reducer_module.SpeechRecognitionSetAssistantListeningAction
        ),
        ReportWakeWordDetectionAction=(
            reducer_module.SpeechRecognitionReportWakeWordDetectionAction
        ),
        WakeTriggerAddAction=reducer_module.WakeTriggerAddAction,
        WakeWordEngineName=reducer_module.WakeWordEngineName,
        WakeMode=reducer_module.WakeMode,
        AssistantStopTalkingAction=reducer_module.AssistantStopTalkingAction,
        QUICK_CHAT_COMMAND_DETECTOR=reducer_module.QUICK_CHAT_COMMAND_DETECTOR,
    )


def _init_state(
    speech: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> SpeechRecognitionState:
    """Build the seeded initial state (persistent store absent -> defaults)."""
    _patch_store(monkeypatch, tmp_path / 'state.json')
    return cast('SpeechRecognitionState', speech.reducer(None, speech.InitAction()))


class TestDefaultCommands:
    """The migrated built-in commands."""

    def test_default_command_count(self, speech: SimpleNamespace) -> None:
        """The full built-in set is seeded (23 originals + time/date/weather)."""
        assert len(speech.commands.DEFAULT_COMMANDS) == 26

    def test_button_three_selects_index_two(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """Legacy mapping used index 1 (a bug); the seed selects item 3."""
        command = next(
            command
            for command in speech.commands.DEFAULT_COMMANDS
            if command.id == 'default:button-three'
        )
        assert command.action_keys == [speech.commands.MENU_CHOOSE_3]

    def test_every_default_has_phrases_and_action_keys(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """Every default command has at least one phrase and action key."""
        for command in speech.commands.DEFAULT_COMMANDS:
            assert command.phrases, command.id
            assert command.action_keys, command.id

    def test_default_ids_are_unique(self, speech: SimpleNamespace) -> None:
        """Default command ids are unique (stable snapshot keys)."""
        ids = [command.id for command in speech.commands.DEFAULT_COMMANDS]
        assert len(ids) == len(set(ids))


class TestEngineRemoval:
    """Google Cloud engine + manual engine selection were removed."""

    def test_state_has_no_selected_engine_field(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The vestigial single-engine ``selected_engine`` field is gone."""
        state = _init_state(speech, monkeypatch, tmp_path)
        assert not hasattr(state, 'selected_engine')

    def test_set_selected_engine_action_no_longer_exists(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """The engine-selection action class was removed from the module."""
        module = speech.reducer.__globals__
        assert 'SpeechRecognitionSetSelectedEngineAction' not in module

    def test_engine_enum_is_vosk_only(self) -> None:
        """Only Vosk remains in the engine-name enum after Google removal."""
        from ubo_app.store.services.speech_recognition import (
            SpeechRecognitionEngineName,
        )

        assert [e.value for e in SpeechRecognitionEngineName] == ['vosk']


class TestBindableCatalog:
    """Registration of the actions backing the default commands."""

    def test_registers_and_resolves_rgb_red(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """The rgb:red key resolves to RgbRingSetAllAction(color=red)."""
        speech.commands.register_default_bindable_actions()
        bindable = speech.get_bindable_action(speech.commands.RGB_RED)
        assert bindable is not None
        action = bindable.factory(_CTX)
        assert type(action).__name__ == 'RgbRingSetAllAction'
        assert getattr(action, 'color', None) == (255, 0, 0)

    def test_menu_choose_three_resolves_to_index_two(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """The menu:choose-3 key selects item index 2 (the fixed mapping)."""
        speech.commands.register_default_bindable_actions()
        bindable = speech.get_bindable_action(speech.commands.MENU_CHOOSE_3)
        assert bindable is not None
        action = bindable.factory(_CTX)
        assert getattr(action, 'index', None) == 2

    def test_registration_is_idempotent(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """A second registration must not raise on already-registered keys."""
        speech.commands.register_default_bindable_actions()
        speech.commands.register_default_bindable_actions()


class TestShortcutActions:
    """One-utterance shortcut actions for the command picker."""

    def test_register_device_resolves_to_direct_action(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """infrared:register-device resolves to InfraredRegisterDeviceAction."""
        speech.commands.register_shortcut_actions()
        bindable = speech.get_bindable_action('infrared:register-device')
        assert bindable is not None
        action = bindable.factory(_CTX)
        assert type(action).__name__ == 'InfraredRegisterDeviceAction'

    def test_flow_openers_resolve_to_execute_menu_action(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """Flow-opener shortcuts dispatch ExecuteMenuActionAction by id."""
        speech.commands.register_shortcut_actions()
        expected = {
            'flow:add-voice-command': 'speech-recognition:add-command',
            'flow:add-application': 'docker:import_composition',
        }
        for key, action_id in expected.items():
            bindable = speech.get_bindable_action(key)
            assert bindable is not None, key
            action = bindable.factory(_CTX)
            assert type(action).__name__ == 'ExecuteMenuActionAction'
            assert getattr(action, 'action_id', None) == action_id

    def test_no_key_or_label_collisions_across_catalog(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """Default + shortcut registrations have unique keys and labels."""
        speech.commands.register_default_bindable_actions()
        speech.commands.register_shortcut_actions()
        bindables = speech.get_bindable_actions()
        keys = [bindable.key for bindable in bindables]
        labels = [bindable.label for bindable in bindables]
        assert len(keys) == len(set(keys))
        assert len(labels) == len(set(labels))

    def test_registration_is_idempotent(
        self,
        speech: SimpleNamespace,
    ) -> None:
        """A second shortcut registration must not raise."""
        speech.commands.register_shortcut_actions()
        speech.commands.register_shortcut_actions()


class TestPersistenceSeeding:
    """Which defaults a device is offered, and when.

    Seeding on "key absent" alone would starve upgraded devices of defaults added
    by later releases; merging every missing default each boot would resurrect the
    ones the user deleted. So we track the ids already *offered* to this device.
    """

    def test_absent_key_seeds_defaults(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A fresh install gets the full default set."""
        _patch_store(monkeypatch, tmp_path / 'missing.json')
        loaded, seeded = speech.commands.load_or_seed_commands()
        assert len(loaded) == 26
        assert len(seeded) == 26

    def test_stored_empty_list_gains_only_unseen_defaults(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An upgraded device that deleted everything gets only the new defaults.

        The pre-tracking defaults were already offered once and deliberately
        removed, so they stay gone; the time/date/weather commands are new and
        have never been offered, so they arrive.
        """
        path = tmp_path / 'state.json'
        path.write_text(json.dumps({'speech_recognition:commands': '[]'}))
        _patch_store(monkeypatch, path)

        loaded, seeded = speech.commands.load_or_seed_commands()

        assert [command.id for command in loaded] == [
            'default:speak-time',
            'default:speak-date',
            'default:speak-weather',
        ]
        assert len(seeded) == 26

    def test_seeded_defaults_are_not_resurrected(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Once a default has been offered, deleting it makes it stay deleted."""
        path = tmp_path / 'state.json'
        path.write_text(
            json.dumps(
                {
                    'speech_recognition:commands': '[]',
                    'speech_recognition:seeded_default_ids': [
                        command.id for command in speech.commands.DEFAULT_COMMANDS
                    ],
                },
            ),
        )
        _patch_store(monkeypatch, path)

        loaded, _seeded = speech.commands.load_or_seed_commands()

        assert loaded == []

    def test_existing_commands_are_preserved_alongside_new_defaults(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An upgrade keeps the user's commands and appends the unseen defaults."""
        path = tmp_path / 'state.json'
        path.write_text(
            json.dumps(
                {
                    'speech_recognition:commands': json.dumps(
                        [
                            {
                                'id': 'custom:tv',
                                'label': 'TV',
                                'phrases': ['turn on the tv'],
                                'action_keys': ['rgb:red'],
                            },
                        ],
                    ),
                },
            ),
        )
        _patch_store(monkeypatch, path)

        loaded, _seeded = speech.commands.load_or_seed_commands()

        ids = [command.id for command in loaded]
        assert ids[0] == 'custom:tv'
        assert 'default:speak-weather' in ids
        # Pre-tracking defaults the user had already removed do not come back.
        assert 'default:lights-red' not in ids

    def test_round_trip_parse(self, speech: SimpleNamespace) -> None:
        """A serialized command list round-trips through the parser."""
        serialized = json.dumps(
            [
                {
                    'id': 'x',
                    'label': 'My Command',
                    'phrases': ['alpha', 'beta'],
                    'action_keys': ['rgb:red', 'audio:volume-up'],
                },
            ],
        )
        parsed = speech.commands.parse_persisted_commands(serialized)
        assert len(parsed) == 1
        assert parsed[0].id == 'x'
        assert parsed[0].label == 'My Command'
        assert parsed[0].phrases == ['alpha', 'beta']
        assert parsed[0].action_keys == ['rgb:red', 'audio:volume-up']


class TestReducerCrud:
    """Add / update / remove command reducer behaviour."""

    def test_add_appends_command(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Add appends a new command to the list."""
        state = _init_state(speech, monkeypatch, tmp_path)
        count = len(state.intents)
        new_state = speech.reducer(
            state,
            speech.AddCommandAction(
                id='c1',
                label='Custom',
                phrases=['hello there'],
                action_keys=['rgb:red'],
            ),
        )
        assert len(new_state.intents) == count + 1
        added = next(i for i in new_state.intents if i.id == 'c1')
        assert added.label == 'Custom'
        assert added.action_keys == ['rgb:red']

    def test_update_replaces_matching_command(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Update replaces only the command with the matching id."""
        state = _init_state(speech, monkeypatch, tmp_path)
        target_id = state.intents[0].id
        count = len(state.intents)
        new_state = speech.reducer(
            state,
            speech.UpdateCommandAction(
                id=target_id,
                label='Renamed',
                phrases=['new phrase'],
                action_keys=['rgb:blue'],
            ),
        )
        assert len(new_state.intents) == count
        updated = next(i for i in new_state.intents if i.id == target_id)
        assert updated.label == 'Renamed'
        assert updated.phrases == ['new phrase']
        assert updated.action_keys == ['rgb:blue']

    def test_remove_deletes_matching_command(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Remove deletes only the command with the matching id."""
        state = _init_state(speech, monkeypatch, tmp_path)
        target_id = state.intents[0].id
        count = len(state.intents)
        new_state = speech.reducer(
            state,
            speech.RemoveCommandAction(id=target_id),
        )
        assert len(new_state.intents) == count - 1
        assert all(i.id != target_id for i in new_state.intents)


class TestIntentDetection:
    """Recognised commands emit a bound-action event (reducer stays pure)."""

    def test_report_intent_emits_event_without_action(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Intent detection emits the bound-action event and dispatches nothing."""
        state = _init_state(speech, monkeypatch, tmp_path)
        waiting = replace(
            state,
            status=speech.SpeechRecognitionStatus.INTENTS_WAITING,
        )
        result = cast(
            'CompleteReducerResult',
            speech.reducer(
                waiting,
                speech.ReportIntentDetectionAction(
                    intent=_tv_intent(speech),
                    text='turn on tv',
                ),
            ),
        )
        assert result.state.status is speech.SpeechRecognitionStatus.IDLE
        # No acknowledgment / dispatched action in the reducer itself.
        assert not result.actions
        events = list(result.events or [])
        assert len(events) == 1
        assert events[0].action_keys == ['infrared:send:nec:0x1', 'rgb:red']
        assert events[0].phrase == 'turn on tv'

    def test_report_intent_while_idle_is_dropped(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A detection with nothing armed is a no-op — this is the exactly-once guard.

        Stage-1 already ran the command and dropped the status back to IDLE; a
        second, later detection of the same utterance must not run it again.
        """
        state = _init_state(speech, monkeypatch, tmp_path)
        result = speech.reducer(
            state,
            speech.ReportIntentDetectionAction(
                intent=_tv_intent(speech),
                text='turn on tv',
            ),
        )
        # Plain state back, no CompleteReducerResult -> no event, no action.
        assert result.status is speech.SpeechRecognitionStatus.IDLE

    def test_report_intent_while_assistant_waiting_runs_and_ends_session(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Stage 1: the command runs and the quick-chat session is torn down.

        ``AssistantStopTalkingAction`` is what discards the turn — without it the
        utterance would go on to reach the LLM and be answered.
        """
        state = _init_state(speech, monkeypatch, tmp_path)
        armed = replace(
            state,
            status=speech.SpeechRecognitionStatus.ASSISTANT_WAITING,
        )
        result = cast(
            'CompleteReducerResult',
            speech.reducer(
                armed,
                speech.ReportIntentDetectionAction(
                    intent=_tv_intent(speech),
                    text='turn on tv',
                ),
            ),
        )
        assert result.state.status is speech.SpeechRecognitionStatus.IDLE
        assert result.state.assistant_session_audio_source == ''

        events = list(result.events or [])
        assert len(events) == 1
        assert events[0].action_keys == ['infrared:send:nec:0x1', 'rgb:red']

        actions = list(result.actions or [])
        assert len(actions) == 1
        assert isinstance(actions[0], speech.AssistantStopTalkingAction)
        assert actions[0].detector == speech.QUICK_CHAT_COMMAND_DETECTOR
        assert actions[0].phrase == 'turn on tv'


class TestAssistantListeningArming:
    """Stage-1 matching is armed for the life of a quick-chat session."""

    def test_arm_from_idle_records_the_audio_source(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Arming moves IDLE -> ASSISTANT_WAITING and remembers the session's mic."""
        state = _init_state(speech, monkeypatch, tmp_path)
        result = speech.reducer(
            state,
            speech.SetAssistantListeningAction(active=True, audio_source='web-1'),
        )
        assert result.status is speech.SpeechRecognitionStatus.ASSISTANT_WAITING
        assert result.assistant_session_audio_source == 'web-1'

    def test_arm_does_not_preempt_the_command_window(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An armed INTENTS window outranks a quick-chat session."""
        state = _init_state(speech, monkeypatch, tmp_path)
        waiting = replace(
            state,
            status=speech.SpeechRecognitionStatus.INTENTS_WAITING,
        )
        result = speech.reducer(
            waiting,
            speech.SetAssistantListeningAction(active=True),
        )
        assert result.status is speech.SpeechRecognitionStatus.INTENTS_WAITING

    def test_disarm_returns_to_idle_and_clears_the_audio_source(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Any assistant stop path disarms stage-1."""
        state = _init_state(speech, monkeypatch, tmp_path)
        armed = replace(
            state,
            status=speech.SpeechRecognitionStatus.ASSISTANT_WAITING,
            assistant_session_audio_source='web-1',
        )
        result = speech.reducer(
            armed,
            speech.SetAssistantListeningAction(active=False),
        )
        assert result.status is speech.SpeechRecognitionStatus.IDLE
        assert result.assistant_session_audio_source == ''

    def test_disarm_leaves_the_command_window_alone(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Disarming must not cancel an INTENTS window it never armed."""
        state = _init_state(speech, monkeypatch, tmp_path)
        waiting = replace(
            state,
            status=speech.SpeechRecognitionStatus.INTENTS_WAITING,
        )
        result = speech.reducer(
            waiting,
            speech.SetAssistantListeningAction(active=False),
        )
        assert result.status is speech.SpeechRecognitionStatus.INTENTS_WAITING


class TestRunCommand:
    """Stage 2: the LLM calls ``run_device_command`` for a near-miss utterance."""

    def test_known_command_emits_its_bound_action_event(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A catalogued id fires the same event stage-1 would have."""
        state = _init_state(speech, monkeypatch, tmp_path)
        target = state.intents[0]
        result = cast(
            'CompleteReducerResult',
            speech.reducer(state, speech.RunCommandAction(command_id=target.id)),
        )
        events = list(result.events or [])
        assert len(events) == 1
        assert events[0].action_keys == target.action_keys
        assert events[0].phrase == target.label

    def test_unknown_command_is_ignored(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An id the LLM invented resolves to nothing rather than crashing."""
        state = _init_state(speech, monkeypatch, tmp_path)
        result = speech.reducer(
            state,
            speech.RunCommandAction(command_id='does-not-exist'),
        )
        assert result is state

    def test_run_command_does_not_need_an_armed_status(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The tool call can land after the session has already ended."""
        state = _init_state(speech, monkeypatch, tmp_path)
        armed = replace(
            state,
            status=speech.SpeechRecognitionStatus.ASSISTANT_WAITING,
        )
        result = cast(
            'CompleteReducerResult',
            speech.reducer(
                armed,
                speech.RunCommandAction(command_id=state.intents[0].id),
            ),
        )
        # Status is left to the assistant's own stop path.
        assert result.state.status is speech.SpeechRecognitionStatus.ASSISTANT_WAITING
        assert len(list(result.events or [])) == 1


class TestCommandsCatalog:
    """The LLM-facing mirror of ``intents`` tracks every write site."""

    def test_seeded_state_has_a_catalog_entry_per_command(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """InitAction builds the catalog, not just the intents."""
        state = _init_state(speech, monkeypatch, tmp_path)
        items = state.commands_catalog.items
        assert len(items) == len(state.intents)
        assert {item.id for item in items} == {i.id for i in state.intents}
        assert all(item.sample_phrases for item in items)

    def test_sample_phrases_are_expanded_and_capped(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Patterns become concrete examples, bounded so the schema stays small."""
        state = _init_state(speech, monkeypatch, tmp_path)
        result = speech.reducer(
            state,
            speech.AddCommandAction(
                id='lamp',
                label='Lamp',
                phrases=['(turn|switch) (on|off) the lamp'],
                action_keys=['rgb:red'],
            ),
        )
        entry = next(i for i in result.commands_catalog.items if i.id == 'lamp')
        assert len(entry.sample_phrases) == 3
        assert 'turn on the lamp' in entry.sample_phrases

    def test_removing_a_command_removes_its_catalog_entry(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Remove is a write site too."""
        state = _init_state(speech, monkeypatch, tmp_path)
        target_id = state.intents[0].id
        result = speech.reducer(
            state,
            speech.RemoveCommandAction(id=target_id),
        )
        assert all(item.id != target_id for item in result.commands_catalog.items)

    def test_updating_a_command_refreshes_its_catalog_entry(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The label the LLM sees follows the label the user set."""
        state = _init_state(speech, monkeypatch, tmp_path)
        target_id = state.intents[0].id
        result = speech.reducer(
            state,
            speech.UpdateCommandAction(
                id=target_id,
                label='Renamed',
                phrases=['do the thing'],
                action_keys=['rgb:red'],
            ),
        )
        entry = next(i for i in result.commands_catalog.items if i.id == target_id)
        assert entry.label == 'Renamed'
        assert entry.sample_phrases == ['do the thing']


class TestIntentTimeout:
    """Listening returns to idle when no command arrives in time."""

    def test_timeout_while_waiting_returns_to_idle(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A timeout in INTENTS_WAITING resets to IDLE with a blank ack."""
        state = _init_state(speech, monkeypatch, tmp_path)
        waiting = replace(
            state,
            status=speech.SpeechRecognitionStatus.INTENTS_WAITING,
        )
        result = cast(
            'CompleteReducerResult',
            speech.reducer(waiting, speech.IntentTimeoutAction()),
        )
        assert result.state.status is speech.SpeechRecognitionStatus.IDLE
        assert result.actions  # RGB blank acknowledgment clears the indicator

    def test_timeout_when_not_waiting_is_noop(
        self,
        speech: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A timeout while idle leaves the state untouched."""
        state = _init_state(speech, monkeypatch, tmp_path)
        result = speech.reducer(state, speech.IntentTimeoutAction())
        # Not in a CompleteReducerResult; the plain state is returned unchanged.
        assert result.status is speech.SpeechRecognitionStatus.IDLE
