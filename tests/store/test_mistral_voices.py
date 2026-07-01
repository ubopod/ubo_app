"""Tests for parsing the Mistral ``GET /v1/audio/voices`` payload."""

from __future__ import annotations

from ubo_app.engines.mistral import _parse_voices_page


def test_parse_prefers_slug_over_uuid() -> None:
    """Voices expose a human ``slug``, which is used as the id when present."""
    payload = {
        'items': [
            {'id': 'uuid-1', 'slug': 'casual_male', 'name': 'Casual Male'},
            {'id': 'uuid-2', 'slug': 'fr_marie_neutral', 'name': 'Marie'},
        ],
        'total': 2,
    }
    entries = _parse_voices_page(payload)
    assert [(entry.id, entry.label) for entry in entries] == [
        ('casual_male', 'Casual Male'),
        ('fr_marie_neutral', 'Marie'),
    ]


def test_parse_falls_back_to_uuid_when_no_slug() -> None:
    """Cloned voices may have only a UUID id (no slug)."""
    payload = {
        'items': [
            {'id': 'uuid-3', 'name': 'My Clone'},
            {'id': 'uuid-4', 'slug': None, 'name': 'Other Clone'},
        ],
    }
    entries = _parse_voices_page(payload)
    assert [(entry.id, entry.label) for entry in entries] == [
        ('uuid-3', 'My Clone'),
        ('uuid-4', 'Other Clone'),
    ]


def test_parse_label_falls_back_to_id() -> None:
    """An unnamed voice labels itself with its id."""
    entries = _parse_voices_page({'items': [{'slug': 'casual_male'}]})
    assert [(entry.id, entry.label) for entry in entries] == [
        ('casual_male', 'casual_male'),
    ]


def test_parse_skips_malformed_entries() -> None:
    """Entries without any id and non-dict entries are dropped, not crashing."""
    payload = {
        'items': [
            {'name': 'NoId'},
            'not-a-dict',
            {'id': 'uuid-5', 'slug': 'pluto', 'name': 'Pluto'},
        ],
    }
    entries = _parse_voices_page(payload)
    assert [entry.id for entry in entries] == ['pluto']


def test_parse_non_dict_payload_is_empty() -> None:
    """A non-dict payload (error body) yields no entries instead of raising."""
    assert _parse_voices_page(None) == []
    assert _parse_voices_page([]) == []
