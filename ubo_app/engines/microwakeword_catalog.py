"""Curated catalog of microWakeWord models available for download.

microWakeWord models are small streaming ``.tflite`` classifiers (45-80 KB)
paired with a ``.json`` manifest carrying the detection parameters. They are a
different family from OpenWakeWord's ~1 MB ONNX models and run on a separate
engine (``microwakeword_engine``).

The models are mirrored from the ``wakewords/`` directory of
`OHF-Voice/linux-voice-assistant <https://github.com/OHF-Voice/linux-voice-assistant>`_
(Apache-2.0), trained by Kevin Ahrendt, Michael Hansen, John Karabudak and
adamlonsdale. Downloads are pinned to :data:`MICROWAKEWORD_COMMIT` rather than
``main`` so a model can't change under a user between releases — bump that
constant to pick up upstream retrains, and re-check the sizes/cutoffs below.

Only the root-level ``type: "micro"`` models are listed. That repo's
``wakewords/openWakeWord/`` subdirectory is deliberately excluded: it holds the
same five models ``openwakeword.MODELS`` already provides, in the ``.tflite``
format our OpenWakeWord engine doesn't load.
"""

from __future__ import annotations

from dataclasses import dataclass

from ubo_app.constants import DATA_PATH

MICROWAKEWORD_COMMIT = '1543c5df583753ab8e4248fc381d75ebaa940f76'
"""Upstream commit the catalog metadata below was read from."""

MICROWAKEWORD_BASE = (
    f'https://raw.githubusercontent.com/OHF-Voice/linux-voice-assistant/'
    f'{MICROWAKEWORD_COMMIT}/wakewords'
)
"""Base URL of the pinned ``wakewords/`` directory.

Files live at ``<base>/<id>.json`` and ``<base>/<id>.tflite``.
"""


@dataclass(frozen=True)
class MicroWakeWordModelEntry:
    """A single microWakeWord model that can be downloaded and run on device."""

    id: str
    """Model id — the stem shared by its ``.json`` and ``.tflite`` files."""

    label: str
    """Wake phrase shown to the user, e.g. ``Hey Jarvis``."""

    size_bytes: int
    """Size of the ``.tflite`` file. The ``.json`` manifest is under 1 KB."""

    probability_cutoff: float
    """Upstream-tuned detection threshold (0.0-1.0).

    Seeds a new trigger's sensitivity as ``1 - probability_cutoff`` so it
    inherits upstream's tuning instead of the generic ``0.5`` default. The
    engine reads the shipped ``.json`` for the same value at load time; this
    copy only exists so the menu can seed the form before the file is on disk.
    """

    trained_languages: tuple[str, ...] = ('en',)
    """Languages the model was trained on."""


MICROWAKEWORD_MODELS: tuple[MicroWakeWordModelEntry, ...] = (
    MicroWakeWordModelEntry(
        id='alexa',
        label='Alexa',
        size_bytes=55856,
        probability_cutoff=0.9,
    ),
    MicroWakeWordModelEntry(
        id='choo_choo_homie',
        label='Choo Choo Homie',
        size_bytes=62112,
        probability_cutoff=0.97,
    ),
    MicroWakeWordModelEntry(
        id='hey_home_assistant',
        label='Hey Home Assistant',
        size_bytes=62112,
        probability_cutoff=0.97,
    ),
    MicroWakeWordModelEntry(
        id='hey_jarvis',
        label='Hey Jarvis',
        size_bytes=52272,
        probability_cutoff=0.97,
    ),
    MicroWakeWordModelEntry(
        id='hey_luna',
        label='Hey Luna',
        size_bytes=75616,
        probability_cutoff=0.63,
    ),
    MicroWakeWordModelEntry(
        id='hey_morgan',
        label='Hey Morgan',
        size_bytes=63520,
        probability_cutoff=0.9,
    ),
    MicroWakeWordModelEntry(
        id='hey_mycroft',
        label='Hey Mycroft',
        size_bytes=57248,
        probability_cutoff=0.95,
    ),
    MicroWakeWordModelEntry(
        id='okay_computer',
        label='Okay Computer',
        size_bytes=62112,
        probability_cutoff=0.97,
    ),
    MicroWakeWordModelEntry(
        id='okay_nabu',
        label='Okay Nabu',
        size_bytes=80824,
        probability_cutoff=0.85,
        trained_languages=('en', 'nl', 'fr', 'de', 'it', 'es', 'sv'),
    ),
    # Upstream hides this one from its wake-word picker because it reserves it
    # for stopping playback. We surface it: it maps directly onto our own
    # ``WakeMode.STOP_TALKING``.
    MicroWakeWordModelEntry(
        id='stop',
        label='Stop',
        size_bytes=45544,
        probability_cutoff=0.5,
    ),
)


_KB = 1024

MODELS_DIR = DATA_PATH / 'microwakeword' / 'models'
"""Where downloaded models live — under the shared data path so they survive
reinstalls, matching OpenWakeWord's ``MODELS_DIR``."""


def all_models() -> tuple[MicroWakeWordModelEntry, ...]:
    """Return every model in the catalog."""
    return MICROWAKEWORD_MODELS


def model_for(model_id: str) -> MicroWakeWordModelEntry | None:
    """Return the catalog entry for *model_id*, if any."""
    return next(
        (model for model in MICROWAKEWORD_MODELS if model.id == model_id),
        None,
    )


def download_urls_for(model_id: str) -> tuple[str, str]:
    """Return the ``(json_url, tflite_url)`` pair for *model_id*."""
    return (
        f'{MICROWAKEWORD_BASE}/{model_id}.json',
        f'{MICROWAKEWORD_BASE}/{model_id}.tflite',
    )


def format_size(size_bytes: int) -> str:
    """Render a model size as a short human-readable label."""
    return f'{size_bytes / _KB:.0f} KB'


def model_label(model: MicroWakeWordModelEntry) -> str:
    """Return the user-facing label for a model in a list menu.

    Example: ``Hey Jarvis · 51 KB``.
    """
    return f'{model.label} · {format_size(model.size_bytes)}'
