"""OpenWakeWord engine for wake word detection.

A dedicated wake-word engine (detection only, no speech recognition) built on the
shared :class:`WakeWordRecognitionMixin` so the :class:`EnginesManager` can drive
it exactly like the Vosk wake-word path: audio arrives via ``queue_audio_chunk``
and detections are pushed onto ``woke_word_recognitions_queue``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from abstraction.wake_word_recognition_mixin import WakeWordRecognitionMixin
from typing_extensions import override

from ubo_app.constants import DATA_PATH
from ubo_app.logger import logger
from ubo_app.store.services.speech_recognition import WakeWordEngineName

if TYPE_CHECKING:
    from collections.abc import Sequence

    from abstraction.wake_word_recognition_mixin import WakeTrigger
    from openwakeword.model import Model

# Audio parameters expected by OpenWakeWord: 16kHz, 16-bit PCM mono.
_CHUNK_SIZE = 1280  # 80ms at 16kHz (openwakeword default)
_BYTES_PER_CHUNK = _CHUNK_SIZE * 2  # 16-bit samples
# Fallback sensitivity (0.0-1.0) when a stem has no configured value; the engine
# activates a model when its confidence is >= ``1 - sensitivity``.
_DEFAULT_SENSITIVITY = 0.5

# Wake-word models live under the shared data path so they survive reinstalls.
MODELS_DIR = DATA_PATH / 'openwakeword' / 'models'

# Helper models that are part of the OpenWakeWord pipeline, not wake words.
_HELPER_MODEL_STEMS = {'embedding_model', 'melspectrogram', 'silero_vad'}
# Shared feature-extractor helpers, passed to ``Model`` directly so we never have
# to copy them into openwakeword's (possibly read-only) package resources dir.
_MELSPEC_PATH = MODELS_DIR / 'melspectrogram.onnx'
_EMBEDDING_PATH = MODELS_DIR / 'embedding_model.onnx'
_SILERO_VAD_PATH = MODELS_DIR / 'silero_vad.onnx'

# Require the Silero VAD to also see speech (score >= this) before a wake-word
# match fires, cutting false activations from non-speech noise. 0.5 is the value
# openWakeWord's bundled models were trained/recommended for.
_VAD_THRESHOLD = 0.5


def scan_models() -> list[str]:
    """Return the loadable wake-word model stems on disk (helpers excluded), sorted.

    Only ``.onnx`` files are listed because :meth:`_load_models` loads that format
    exclusively — so every stem the UI shows is actually loadable.
    """
    if not MODELS_DIR.exists():
        return []
    stems = {
        path.stem
        for path in MODELS_DIR.glob('*.onnx')
        if path.stem not in _HELPER_MODEL_STEMS
    }
    return sorted(stems)


def is_loadable_onnx(data: bytes) -> bool:
    """Whether *data* is a structurally valid ONNX model (loadable by onnxruntime).

    Guards uploads: arbitrary bytes saved as ``<stem>.onnx`` would otherwise show
    up in the model list yet fail to load. Returns True (skip the check) only when
    onnxruntime itself can't be imported, so validation never blocks unexpectedly.
    """
    try:
        import onnxruntime
    except ImportError:
        logger.warning('onnxruntime unavailable; skipping uploaded-model validation')
        return True
    try:
        onnxruntime.InferenceSession(
            data,
            providers=['CPUExecutionProvider'],
        )
    except Exception:
        logger.exception('Uploaded file is not a loadable ONNX model')
        return False
    return True


def helpers_available() -> bool:
    """Whether the shared feature-extractor helpers are on disk (Model needs them)."""
    return all(
        (MODELS_DIR / f'{stem}.onnx').exists()
        for stem in ('embedding_model', 'melspectrogram')
    )


# NOTE: ``Model`` is handed the melspectrogram/embedding paths explicitly (via its
# ``**kwargs`` → ``AudioFeatures``) so it loads our downloaded feature extractors
# directly instead of reading — and us copying into — its package resources dir,
# which is fragile under read-only / system installs.


def _enable_vad(model: Model) -> None:
    """Turn on Silero VAD for *model*, gated on our downloaded VAD file.

    ``Model`` builds its VAD from the package resources dir with no path override,
    and we deliberately don't populate that dir — so we inject a VAD pointed at our
    ``MODELS_DIR`` copy and set the threshold post-construction (``predict`` runs
    the VAD whenever ``vad_threshold > 0``). Best-effort: a missing file or import
    just leaves VAD off rather than failing the load.
    """
    if not _SILERO_VAD_PATH.exists():
        logger.warning(
            'Silero VAD model not downloaded; VAD disabled',
            extra={'path': _SILERO_VAD_PATH},
        )
        return
    try:
        import openwakeword

        model.vad = openwakeword.VAD(model_path=str(_SILERO_VAD_PATH))
        model.vad_threshold = _VAD_THRESHOLD
    except Exception:
        logger.exception('Failed to enable Silero VAD')


def _enable_noise_suppression(model: Model) -> None:
    """Turn on Speex noise suppression for *model* if available.

    ``speexdsp_ns`` is a native, Linux (x86/arm64)-only dependency, so on platforms
    without it (e.g. macOS dev) suppression simply stays off. Wired post-construction
    so we don't have to pass ``enable_speex_noise_suppression`` to ``Model`` (which
    would hard-import the package and fail the whole load when it's absent).
    """
    try:
        # Optional native dependency (Linux x86/arm64 only); absent on e.g. macOS.
        from speexdsp_ns import (  # pyright: ignore[reportMissingImports]
            NoiseSuppression,
        )
    except ImportError:
        logger.info('speexdsp_ns unavailable; Speex noise suppression disabled')
        return
    try:
        # 160 samples (10 ms) per frame at 16 kHz, matching openWakeWord's own setup.
        model.speex_ns = NoiseSuppression.create(160, 16000)
    except Exception:
        logger.exception('Failed to enable Speex noise suppression')


def validate_openwakeword_model(data: bytes) -> bool:
    """Whether *data* loads and predicts as an OpenWakeWord model.

    Runs the real ``Model(..., inference_framework='onnx')`` path on a temp copy
    plus a one-frame silence prediction, so a structurally-valid ONNX with the
    wrong I/O shape (which ``is_loadable_onnx`` would accept) is caught. Falls back
    to the structural onnx check when openwakeword/numpy or the shared helper
    models aren't available — so a custom upload made before the default models are
    downloaded isn't falsely rejected.
    """
    try:
        import numpy as np
        import openwakeword  # noqa: F401
        from openwakeword.model import Model
    except ImportError:
        return is_loadable_onnx(data)
    if not helpers_available():
        return is_loadable_onnx(data)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / 'candidate.onnx'
        candidate.write_bytes(data)
        try:
            model = Model(
                wakeword_models=[str(candidate)],
                inference_framework='onnx',
                melspec_model_path=str(_MELSPEC_PATH),
                embedding_model_path=str(_EMBEDDING_PATH),
            )
            model.predict(np.zeros(_CHUNK_SIZE, dtype=np.int16))
        except Exception:
            logger.exception('Uploaded file is not a valid OpenWakeWord model')
            return False
    return True


def delete_model(model_id: str) -> None:
    """Delete the model files for *model_id* (``.onnx``/``.tflite``) from disk.

    ``model_id`` may arrive from a remote (gRPC-dispatched) action, so it is
    treated as untrusted: anything that isn't a bare filename living directly in
    :data:`MODELS_DIR` (path separators, ``..``, absolute paths) is rejected
    before any filesystem operation, so a crafted id can't unlink files elsewhere.
    Shared helper models (feature extractor / VAD) are also refused — deleting one
    would break every wake-word model.
    """
    if not model_id or Path(model_id).name != model_id:
        logger.warning(
            'Refusing to delete model with invalid id',
            extra={'model_id': model_id},
        )
        return
    if model_id in _HELPER_MODEL_STEMS:
        logger.warning(
            'Refusing to delete shared OpenWakeWord helper model',
            extra={'model_id': model_id},
        )
        return
    base = MODELS_DIR.resolve()
    for suffix in ('.onnx', '.tflite'):
        path = (base / f'{model_id}{suffix}').resolve()
        if not path.is_relative_to(base):
            logger.warning(
                'Refusing to delete model outside MODELS_DIR',
                extra={'path': path},
            )
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception(
                'Failed to delete OpenWakeWord model',
                extra={'path': path},
            )


def default_model_names() -> list[str]:
    """Return the default OpenWakeWord wake-word model names.

    One entry per pre-trained wake word (e.g. ``hey_jarvis``); the caller
    downloads them one at a time to drive a per-model progress notification.
    Empty if the package isn't installed.
    """
    try:
        import openwakeword
    except ImportError:
        logger.exception('openwakeword package not installed')
        return []
    return list(openwakeword.MODELS)


def download_model(name: str) -> None:
    """Download one default model (its ``.onnx`` + ``.tflite``) into MODELS_DIR.

    Shared feature/VAD helpers are fetched on the first call. Idempotent —
    openwakeword skips files already on disk.

    Raises:
        ImportError: If the ``openwakeword`` package is not installed.
        RuntimeError: If the download fails.

    """
    try:
        from openwakeword.utils import download_models as _download
    except ImportError as error:
        msg = 'openwakeword package not installed'
        logger.exception(msg)
        raise ImportError(msg) from error

    try:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info('Downloading OpenWakeWord model', extra={'model': name})
        _download([name], str(MODELS_DIR))
    except Exception as error:
        msg = f'Failed to download OpenWakeWord model {name}: {error!s}'
        logger.exception(msg)
        raise RuntimeError(msg) from error


class OpenWakeWordEngine(WakeWordRecognitionMixin):
    """OpenWakeWord wake-word detection engine."""

    def __init__(self) -> None:
        """Initialize the OpenWakeWord engine."""
        self._model: Model | None = None
        self._audio_buffer = bytearray()
        # Maps of enabled model stem -> trigger id and -> sensitivity, plus the
        # signature of the currently-loaded model set (so we only rebuild on change).
        self._stem_to_id: dict[str, str] = {}
        self._stem_to_sensitivity: dict[str, float] = {}
        self._loaded_signature: tuple[str, ...] | None = None
        super().__init__(label='OpenWakeWord')

    @property
    @override
    def name(self) -> str:
        return WakeWordEngineName.OPENWAKEWORD

    @property
    @override
    def label(self) -> str:
        return 'OpenWakeWord'

    @override
    def set_triggers(self, triggers: Sequence[WakeTrigger] | None) -> None:
        """Set the triggers and (re)load only the enabled models on change."""
        super().set_triggers(triggers)
        self._stem_to_id = {trigger.value: trigger.id for trigger in self.triggers}
        self._stem_to_sensitivity = {
            trigger.value: trigger.sensitivity for trigger in self.triggers
        }
        # Signature reflects the requested stems that actually exist on disk, not
        # just the requested set: a model whose file arrives later (e.g. finishes
        # downloading) changes the signature and triggers a reload, instead of the
        # signature committing to a set that ``_load_models`` only partially loaded.
        signature = tuple(
            sorted(
                stem
                for stem in self._stem_to_id
                if (MODELS_DIR / f'{stem}.onnx').exists()
            ),
        )
        if signature == self._loaded_signature:
            return
        self._model = None
        self._audio_buffer.clear()
        if not signature:
            # No enabled models — nothing to load, treat as a committed empty state.
            self._loaded_signature = signature
            return
        try:
            self._load_models()
        except (FileNotFoundError, ImportError, RuntimeError):
            # Leave the signature uncommitted so a later sync (e.g. once the model
            # is downloaded) retries the load instead of short-circuiting.
            self._loaded_signature = None
            logger.exception(
                'Failed to load OpenWakeWord models',
                extra={'models_dir': MODELS_DIR},
            )
        else:
            self._loaded_signature = signature

    def _load_models(self) -> None:
        """Load the OpenWakeWord models from :data:`MODELS_DIR`.

        Raises:
            FileNotFoundError: If no wake-word model files are present.
            ImportError: If the ``openwakeword`` package is not installed.
            RuntimeError: If model loading fails.

        """
        # Load only the models referenced by the (enabled) triggers.
        wake_word_models = [
            str(path)
            for path in MODELS_DIR.glob('*.onnx')
            if path.stem in self._stem_to_id
        ]
        if not wake_word_models:
            msg = f'No enabled OpenWakeWord models found in {MODELS_DIR}'
            raise FileNotFoundError(msg)

        try:
            from openwakeword.model import Model

            model = Model(
                wakeword_models=wake_word_models,
                inference_framework='onnx',
                melspec_model_path=str(_MELSPEC_PATH),
                embedding_model_path=str(_EMBEDDING_PATH),
            )
            _enable_vad(model)
            _enable_noise_suppression(model)
            self._model = model
            logger.info(
                'OpenWakeWord models loaded',
                extra={'models': list(model.models.keys())},
            )
        except ImportError as error:
            msg = 'openwakeword package not installed'
            logger.exception(msg)
            raise ImportError(msg) from error
        except Exception as error:
            msg = f'Failed to load OpenWakeWord models from {MODELS_DIR}'
            logger.exception(msg)
            raise RuntimeError(msg) from error

    @override
    async def _run(self) -> None:
        """Consume mic audio and push detected wake words onto the queue."""
        while self.should_be_running():
            chunk = await self.input_queue.get()
            if self._model is None:
                # No model yet (not downloaded / failed to load). Drop audio and
                # keep the loop alive so a runtime download self-heals.
                self._audio_buffer.clear()
                continue

            self._audio_buffer.extend(chunk)
            while len(self._audio_buffer) >= _BYTES_PER_CHUNK:
                frame = bytes(self._audio_buffer[:_BYTES_PER_CHUNK])
                del self._audio_buffer[:_BYTES_PER_CHUNK]
                await self._process_frame(frame)

    async def _process_frame(self, frame: bytes) -> None:
        """Run inference on one frame and queue any matching wake word."""
        if self._model is None:
            return
        audio = np.frombuffer(frame, dtype=np.int16)
        result = await asyncio.to_thread(self._model.predict, audio)
        predictions: dict[str, float] = (
            result[0] if isinstance(result, tuple) else result
        )
        for model_name, confidence in predictions.items():
            # Per-model activation: higher sensitivity → lower required confidence.
            sensitivity = self._stem_to_sensitivity.get(
                model_name,
                _DEFAULT_SENSITIVITY,
            )
            if confidence < 1 - sensitivity:
                continue
            # The prediction key is the loaded model's file stem, which is exactly
            # a trigger's ``value`` — route by id with no fuzzy matching.
            trigger_id = self._stem_to_id.get(model_name)
            if trigger_id is None:
                continue
            logger.info(
                'OpenWakeWord detected wake word',
                extra={
                    'model': model_name,
                    'confidence': float(confidence),
                    'sensitivity': sensitivity,
                },
            )
            await self.woke_word_recognitions_queue.put(trigger_id)
            break
