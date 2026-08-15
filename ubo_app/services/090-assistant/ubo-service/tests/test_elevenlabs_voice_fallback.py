"""Voice resolution for ElevenLabs TTS when no voice id is configured.

The ElevenLabs voice id became optional at setup (an API key alone is enough,
and also unlocks ElevenLabs STT). TTS therefore resolves its voice through
picked voice → ``elevenlabs_voice_id`` secret → default-library voice. The
ordering is the load-bearing part: users who configured a voice id back when it
was mandatory must keep hearing that voice, not the new default.
"""

from __future__ import annotations

import unittest

from ubo_assistant.ubo_tts import (
    DEFAULT_ELEVENLABS_TTS_VOICE,
    TTSServiceConfig,
    UboTTSService,
)


def _voice_for(config: TTSServiceConfig) -> object:
    """Build the ElevenLabs service off *config* and report its voice."""
    # ``__new__`` skips the heavy switcher __init__ (needs a live RPC client);
    # ``_create_elevenlabs_service`` only reads ``self._config``.
    service = UboTTSService.__new__(UboTTSService)
    service._config = config  # noqa: SLF001
    built = service._create_elevenlabs_service()  # noqa: SLF001
    return None if built is None else built._settings.voice  # noqa: SLF001


class ElevenLabsVoiceFallbackTests(unittest.TestCase):
    """Picked voice beats the secret, which beats the default."""

    def test_no_api_key_builds_nothing(self) -> None:
        """The API key is still the one hard requirement."""
        self.assertIsNone(_voice_for(TTSServiceConfig()))  # noqa: PT009

    def test_api_key_alone_falls_back_to_the_default_voice(self) -> None:
        """An API-key-only setup still yields a working TTS service."""
        self.assertEqual(  # noqa: PT009
            _voice_for(TTSServiceConfig(elevenlabs_api_key='sk_test')),
            DEFAULT_ELEVENLABS_TTS_VOICE,
        )

    def test_stored_secret_wins_over_the_default(self) -> None:
        """Pre-existing configured voices keep working unchanged."""
        self.assertEqual(  # noqa: PT009
            _voice_for(
                TTSServiceConfig(
                    elevenlabs_api_key='sk_test',
                    elevenlabs_voice_id='secretvoiceid00000000',
                ),
            ),
            'secretvoiceid00000000',
        )

    def test_picked_voice_wins_over_the_secret(self) -> None:
        """An explicit selection in the picker overrides everything."""
        self.assertEqual(  # noqa: PT009
            _voice_for(
                TTSServiceConfig(
                    elevenlabs_api_key='sk_test',
                    elevenlabs_voice_id='secretvoiceid00000000',
                    selected_voices={'elevenlabs': 'pickedvoiceid00000000'},
                ),
            ),
            'pickedvoiceid00000000',
        )


if __name__ == '__main__':
    unittest.main()
