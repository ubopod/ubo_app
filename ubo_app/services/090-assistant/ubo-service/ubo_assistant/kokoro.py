"""Kokoro text-to-speech service for pipecat.

Thin wrapper around pipecat's ``KokoroTTSService`` that:

* Passes explicit ``model_path`` / ``voices_path`` so the engine never
  auto-downloads to ``~/.cache/kokoro-onnx/`` — the core process owns
  the download lifecycle (progress notifications, error handling,
  on-disk location under ``DATA_PATH/kokoro``).
* Exposes ``request_voice`` so the ``UboTTSService`` autorun on
  ``state.assistant.selected_kokoro_voice`` can switch voices on the
  fly. Kokoro keeps every voice in the already-loaded
  ``voices-v1.0.bin``, so a voice switch is just a settings rewrite —
  no file reload is needed.
* Works around a packaging bug in ``espeakng-loader``'s bundled
  espeak-ng 1.52: that build strips the literal segment
  ``/espeak-ng-data`` from whatever path you give ``espeak_Initialize``,
  then looks up ``phontab`` directly in the leftover parent. The result
  is errors like ``espeakng_loader//phontab: No such file or directory``
  on every utterance. The patch in this module rewrites
  :func:`espeakng_loader.get_data_path` to return a sibling symlink
  whose last segment is NOT ``espeak-ng-data``, so espeak's strip
  becomes a no-op and the actual data files are found.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import espeakng_loader as _espeakng_loader

from ubo_assistant.constants import DATA_PATH


def _patch_espeakng_data_path() -> None:
    """Replace ``espeakng_loader.get_data_path`` with an alias-returning version.

    espeak-ng 1.52 (bundled with ``espeakng-loader`` 0.2.4) has a bug
    where it strips a trailing ``/espeak-ng-data`` from the path it
    receives via ``espeak_Initialize``, then looks for files in the
    leftover parent. The bundled data dir IS literally named
    ``espeak-ng-data``, so as-shipped the lookup goes to
    ``espeakng_loader//phontab`` and fails on every utterance.

    A symlink alone is not enough: phonemizer's ``EspeakWrapper.data_path``
    calls ``pathlib.Path(...).resolve()`` before handing the path to
    espeak, which collapses any symlink back to the canonical
    ``espeak-ng-data`` name. So instead we **copy** the data tree once
    to a stable location under ``DATA_PATH/kokoro/espeak_data`` —
    a directory whose canonical name is ``espeak_data`` (no offending
    suffix), so espeak uses it as-is.

    Both ``kokoro_onnx`` and the ``phonemizer`` wrapper call
    ``espeakng_loader.get_data_path()`` to populate the espeak config,
    so a single monkey-patch covers every caller.

    Falls through to the original path on any OS error (read-only fs,
    permission denied, …); the upstream error will still surface but at
    least we tried.
    """
    real_data = Path(_espeakng_loader.get_data_path())
    if not real_data.exists():
        # Nothing we can do — let upstream raise its own error.
        return

    dest = DATA_PATH / 'kokoro' / 'espeak_data'

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # ``phontab`` is a small required file; its presence is the
        # cheapest proxy for "data tree already mirrored". Re-copy when
        # missing or when the real data dir is newer (mirror cache).
        phontab = dest / 'phontab'
        needs_copy = (
            not phontab.exists()
            or phontab.stat().st_mtime < (real_data / 'phontab').stat().st_mtime
        )
        if needs_copy:
            # ``dirs_exist_ok`` keeps the call idempotent across
            # restarts; on first boot it lays down the full tree.
            shutil.copytree(real_data, dest, dirs_exist_ok=True)
    except OSError:
        return

    dest_str = str(dest)
    _espeakng_loader.get_data_path = lambda: dest_str


# Apply the patch at import time — must run BEFORE pipecat's
# ``KokoroTTSService.__init__`` constructs ``Kokoro``, which in turn
# instantiates the phonemizer wrapper.
_patch_espeakng_data_path()


from pipecat.services.kokoro.tts import (  # noqa: E402 — patch must run first
    KokoroTTSService as PipecatKokoroTTSService,
)
from pipecat.services.settings import TTSSettings  # noqa: E402
from pipecat.transcriptions.language import Language  # noqa: E402

DEFAULT_KOKORO_VOICE_ID = 'af_heart'

KOKORO_DIR: Path = DATA_PATH / 'kokoro'
MODEL_PATH: Path = KOKORO_DIR / 'kokoro-v1.0.onnx'
VOICES_PATH: Path = KOKORO_DIR / 'voices-v1.0.bin'


def _language_for(voice_id: str) -> Language:
    """Map a voice id prefix to the pipecat ``Language`` enum.

    The naming convention is documented at
    https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md —
    first character is the language family code (``a`` American
    English, ``b`` British English, ``e`` Spanish, ``f`` French,
    ``h`` Hindi, ``i`` Italian, ``j`` Japanese, ``p`` Portuguese,
    ``z`` Mandarin Chinese).
    """
    prefix = voice_id[:1] if voice_id else 'a'
    return {
        'a': Language.EN_US,
        'b': Language.EN_GB,
        'e': Language.ES,
        'f': Language.FR,
        'h': Language.HI,
        'i': Language.IT,
        'j': Language.JA,
        'p': Language.PT,
        'z': Language.ZH,
    }.get(prefix, Language.EN_US)


class KokoroTTSService(PipecatKokoroTTSService):
    """Ubo-flavoured Kokoro service with deterministic file paths."""

    def __init__(
        self,
        *,
        voice_id: str = DEFAULT_KOKORO_VOICE_ID,
    ) -> None:
        """Initialise the Kokoro service with our managed on-disk files."""
        super().__init__(
            model_path=str(MODEL_PATH),
            voices_path=str(VOICES_PATH),
            settings=PipecatKokoroTTSService.Settings(
                voice=voice_id,
                language=_language_for(voice_id),
            ),
        )
        # ``_requested_voice_id`` mirrors what the user has asked for;
        # the parent class stores the active config in ``_settings``.
        # We expose ``request_voice`` for the ``UboTTSService`` autorun
        # to write here from any thread — the next ``run_tts`` then
        # reads ``_settings`` for the chosen voice. Plain attribute
        # assignment is fine: no per-utterance file work needed because
        # all voices live in the already-loaded ``voices-v1.0.bin``.
        self._requested_voice_id = voice_id

    def request_voice(self, voice_id: str) -> None:
        """Record the voice the user selected and rewrite settings.

        The ``language`` field MUST be the service-specific lowercase
        string (e.g. ``"en-us"``) that ``kokoro-onnx`` forwards to the
        ``phonemizer`` espeak backend. Pipecat's ``TTSService.__init__``
        runs ``language_to_service_language`` to perform this
        conversion, but we replace ``_settings`` wholesale here and so
        must do the conversion ourselves — otherwise phonemizer sees
        the raw enum value (``"en-US"``) and rejects every utterance
        with ``language "en-US" is not supported by the espeak backend``.
        """
        if not voice_id:
            return
        self._requested_voice_id = voice_id
        language = self.language_to_service_language(_language_for(voice_id))
        self._settings = TTSSettings(  # pyright: ignore[reportAttributeAccessIssue]
            model=None,
            voice=voice_id,
            language=language,
        )
