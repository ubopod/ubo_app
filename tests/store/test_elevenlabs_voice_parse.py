"""Tests for parsing the ElevenLabs ``GET /v2/voices`` payload."""

from __future__ import annotations

from ubo_app.engines.elevenlabs import _parse_voices_page


def test_parse_extracts_id_and_name() -> None:
    """Well-formed voice objects become ``ElevenLabsVoiceEntry`` items."""
    payload = {
        'voices': [
            {'voice_id': 'v1', 'name': 'Rachel', 'category': 'premade'},
            {'voice_id': 'v2', 'name': 'Adam', 'category': 'cloned'},
        ],
        'has_more': False,
    }
    entries = _parse_voices_page(payload)
    assert [(entry.id, entry.label) for entry in entries] == [
        ('v1', 'Rachel'),
        ('v2', 'Adam'),
    ]


def test_parse_skips_malformed_entries() -> None:
    """Missing/empty ids and non-dict entries are dropped, not crashing."""
    payload = {
        'voices': [
            {'voice_id': '', 'name': 'NoId'},
            {'name': 'MissingId'},
            'not-a-dict',
            {'voice_id': 'v3', 'name': 'Bella'},
        ],
    }
    entries = _parse_voices_page(payload)
    assert [entry.id for entry in entries] == ['v3']


def test_parse_non_dict_payload_is_empty() -> None:
    """A non-dict payload (error body) yields no entries instead of raising."""
    assert _parse_voices_page(None) == []
    assert _parse_voices_page([]) == []
