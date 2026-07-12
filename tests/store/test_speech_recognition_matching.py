"""Unit tests for the armed-grammar matching logic (``matching.py``).

The grammar the EnginesManager arms holds two phrase sets at once: the voice
shortcuts, and the Vosk stop-talking phrases (which are otherwise deaf while a
recognition is ongoing — see ``stop_talking_triggers``). These cover how a
recognition is routed back to one set or the other.

The module lives in a hyphenated service directory, so it is loaded by file path
(mirroring ``test_speech_recognition_commands``).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVICE_PATH = (
    Path(__file__).resolve().parents[2]
    / 'ubo_app'
    / 'services'
    / '090-speech-recognition'
)


@pytest.fixture
def matching(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Load ``matching`` from the service dir, plus the store types it returns."""
    monkeypatch.syspath_prepend(SERVICE_PATH.as_posix())
    sr = importlib.import_module('ubo_app.store.services.speech_recognition')

    spec = importlib.util.spec_from_file_location(
        'speech_recognition_matching',
        SERVICE_PATH / 'matching.py',
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return SimpleNamespace(
        expand_phrases=module.expand_phrases,
        stop_talking_triggers=module.stop_talking_triggers,
        match_recognition=module.match_recognition,
        Intent=sr.SpeechRecognitionIntent,
        Trigger=sr.WakeWordTrigger,
        EngineConfig=sr.WakeWordEngineConfig,
        Engine=sr.WakeWordEngineName,
        WakeMode=sr.WakeMode,
        IntentDetection=sr.SpeechRecognitionReportIntentDetectionAction,
        WakeDetection=sr.SpeechRecognitionReportWakeWordDetectionAction,
    )


def _intent(matching: SimpleNamespace, **kwargs: object) -> object:
    defaults = {
        'id': 'lights',
        'label': 'Lights',
        'phrases': ['turn on the lights'],
        'action_keys': ['rgb:red'],
    }
    return matching.Intent(**{**defaults, **kwargs})


def _vosk(
    matching: SimpleNamespace,
    *triggers: object,
    enabled: bool = True,
) -> object:
    return matching.EngineConfig(
        engine=matching.Engine.VOSK,
        enabled=enabled,
        triggers=tuple(triggers),
    )


def _stop_trigger(
    matching: SimpleNamespace,
    value: str,
    trigger_id: str = 's1',
) -> object:
    return matching.Trigger(
        id=trigger_id,
        label=value,
        mode=matching.WakeMode.STOP_TALKING,
        value=value,
    )


class TestStopTalkingTriggers:
    """Which stop phrases get folded into the armed grammar."""

    def test_collects_enabled_vosk_stop_phrases(
        self,
        matching: SimpleNamespace,
    ) -> None:
        """Stop-talking triggers map their (lowercased) phrase to their id."""
        config = _vosk(matching, _stop_trigger(matching, 'Okay Enough'))
        assert matching.stop_talking_triggers([config]) == {'okay enough': 's1'}

    def test_ignores_non_stop_modes(self, matching: SimpleNamespace) -> None:
        """A wake phrase is not a stop phrase; re-waking mid-session is not a thing."""
        wake = matching.Trigger(
            id='w1',
            label='hey ubo',
            mode=matching.WakeMode.QUICK_CHAT,
            value='hey ubo',
        )
        assert matching.stop_talking_triggers([_vosk(matching, wake)]) == {}

    def test_ignores_a_disabled_engine(self, matching: SimpleNamespace) -> None:
        """A disabled Vosk engine has no live triggers to honour."""
        config = _vosk(
            matching,
            _stop_trigger(matching, 'okay enough'),
            enabled=False,
        )
        assert matching.stop_talking_triggers([config]) == {}

    def test_ignores_other_engines(self, matching: SimpleNamespace) -> None:
        """OpenWakeWord trigger values are model ids, not phrases — not grammar."""
        config = matching.EngineConfig(
            engine=matching.Engine.OPENWAKEWORD,
            enabled=True,
            triggers=(_stop_trigger(matching, 'hey_jarvis'),),
        )
        assert matching.stop_talking_triggers([config]) == {}


class TestMatchRecognition:
    """Routing a recognition back to a command or a stop."""

    def test_command_phrase_reports_intent_detection(
        self,
        matching: SimpleNamespace,
    ) -> None:
        """A shortcut phrase resolves to its intent."""
        intent = _intent(matching)
        action = matching.match_recognition('turn on the lights', [intent], {})
        assert isinstance(action, matching.IntentDetection)
        assert action.intent is intent
        assert action.text == 'turn on the lights'

    def test_patterns_are_expanded(self, matching: SimpleNamespace) -> None:
        """The grammar is the expansion, so matching has to expand too."""
        intent = _intent(matching, phrases=['(turn|switch) on the lights'])
        action = matching.match_recognition('switch on the lights', [intent], {})
        assert isinstance(action, matching.IntentDetection)

    def test_stop_phrase_reports_a_wake_detection(
        self,
        matching: SimpleNamespace,
    ) -> None:
        """A stop phrase re-enters the normal wake path, which maps it to a stop."""
        action = matching.match_recognition(
            'okay enough',
            [],
            {'okay enough': 's1'},
        )
        assert isinstance(action, matching.WakeDetection)
        assert action.trigger_id == 's1'
        assert action.engine_name == 'vosk'
        assert action.phrase == 'okay enough'

    def test_stop_phrase_matches_as_a_substring(
        self,
        matching: SimpleNamespace,
    ) -> None:
        """Mirrors how the wake mixin matches wake words."""
        action = matching.match_recognition('okay enough now', [], {'enough': 's1'})
        assert isinstance(action, matching.WakeDetection)

    def test_a_command_containing_the_stop_phrase_still_runs_the_command(
        self,
        matching: SimpleNamespace,
    ) -> None:
        """Commands are matched first — otherwise a "stop" trigger would eat them.

        With a stop phrase of "stop", the shortcut "stop the music" must not be
        mistaken for a barge-in.
        """
        intent = _intent(matching, id='music', phrases=['stop the music'])
        action = matching.match_recognition(
            'stop the music',
            [intent],
            {'stop': 's1'},
        )
        assert isinstance(action, matching.IntentDetection)
        assert action.intent is intent

    def test_unmatched_text_resolves_to_nothing(
        self,
        matching: SimpleNamespace,
    ) -> None:
        """`[unk]` noise from the grammar is dropped rather than dispatched."""
        intent = _intent(matching)
        action = matching.match_recognition(
            'what is the weather',
            [intent],
            {'okay enough': 's1'},
        )
        assert action is None

    def test_matching_is_case_insensitive(self, matching: SimpleNamespace) -> None:
        """Vosk emits lowercase, but the deferred cloud-STT source will not."""
        intent = _intent(matching)
        action = matching.match_recognition('Turn On The Lights', [intent], {})
        assert isinstance(action, matching.IntentDetection)
        # The original casing is preserved for the event's phrase.
        assert action.text == 'Turn On The Lights'


class TestExpandPhrases:
    """A malformed pattern must not take the whole command set down."""

    def test_invalid_pattern_falls_back_to_a_literal(
        self,
        matching: SimpleNamespace,
    ) -> None:
        """An unbalanced pattern is used verbatim rather than raising."""
        assert matching.expand_phrases(['(unbalanced']) == ['(unbalanced']
