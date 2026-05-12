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

from ubo_bindings.ubo.v1 import AssistantLlmName

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


if __name__ == '__main__':
    unittest.main()
