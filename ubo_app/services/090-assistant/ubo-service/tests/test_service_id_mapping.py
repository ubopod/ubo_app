"""Drift-guard test for ``_SERVICE_ID_BY_LLM_NAME`` in ``ubo_assistant.ubo_llm``.

The proto enum ``AssistantLlmName`` (parent-side) maps to the subprocess's
``self._services`` keys via ``_SERVICE_ID_BY_LLM_NAME``. If a new LLM is
added to ``AssistantLLMName`` without updating this dict,
``_handle_model_changed_event`` silently ignores its model-change events —
user-visible symptom is "picking a model for provider X has no effect on
the active service".
"""

from __future__ import annotations

import unittest

from ubo_bindings.ubo.v1 import (
    AssistantLlmName,
    AssistantSttName,
    AssistantTtsName,
)

from ubo_assistant.request_handler import (
    _LLM_PROVIDER_IDS,
    _STT_PROVIDER_IDS,
    _TTS_PROVIDER_IDS,
)
from ubo_assistant.ubo_llm import _SERVICE_ID_BY_LLM_NAME


class TestServiceIdMappingCoverage(unittest.TestCase):
    """The mapping must cover every non-sentinel proto enum member."""

    def test_every_proto_member_has_a_service_id(self) -> None:
        """Fail if a new proto enum entry has no mapping."""
        members = [
            member
            for member in AssistantLlmName
            if 'UNSPECIFIED' not in (member.name or '')
        ]
        missing = [m for m in members if m not in _SERVICE_ID_BY_LLM_NAME]
        self.assertEqual(  # noqa: PT009
            missing,
            [],
            (
                f'_SERVICE_ID_BY_LLM_NAME is missing entries for: {missing!r}. '
                'Add them so _handle_model_changed_event can route their '
                'events.'
            ),
        )


class TestOneShotProviderIdCoverage(unittest.TestCase):
    """The one-shot ``request_handler`` maps must cover every proto member.

    These maps key by proto enum *name* (e.g. ``'MISTRAL'``) and route the
    decoupled screen-reader/one-shot pipeline. A missing entry resolves to
    ``provider_id=None`` → the stage builds no service → silent output (the
    live conversation pipeline uses a *different* map, so the gap is invisible
    there). This guards both maps in lockstep.
    """

    def _assert_covers(self, enum: object, mapping: dict[str, str]) -> None:
        names = [
            member.name
            for member in enum  # pyright: ignore[reportGeneralTypeIssues]
            if 'UNSPECIFIED' not in (member.name or '')
        ]
        missing = [name for name in names if name not in mapping]
        self.assertEqual(missing, [])  # noqa: PT009

    def test_stt_provider_ids_cover_proto(self) -> None:
        """Every STT proto member routes in the one-shot map."""
        self._assert_covers(AssistantSttName, _STT_PROVIDER_IDS)

    def test_llm_provider_ids_cover_proto(self) -> None:
        """Every LLM proto member routes in the one-shot map."""
        self._assert_covers(AssistantLlmName, _LLM_PROVIDER_IDS)

    def test_tts_provider_ids_cover_proto(self) -> None:
        """Every TTS proto member routes in the one-shot map."""
        self._assert_covers(AssistantTtsName, _TTS_PROVIDER_IDS)


if __name__ == '__main__':
    unittest.main()
