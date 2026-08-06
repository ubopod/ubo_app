"""microWakeWord engine for wake word detection.

A detection-only engine (no speech recognition) built on the shared
:class:`WakeWordRecognitionMixin`, so the :class:`EnginesManager` drives it
exactly like the OpenWakeWord path: audio arrives via ``queue_audio_chunk`` and
detections are pushed onto ``woke_word_recognitions_queue``.

microWakeWord models are streaming ``.tflite`` classifiers an order of magnitude
smaller and cheaper than OpenWakeWord's ONNX models. Each is a *pair* on disk —
``<id>.tflite`` plus an ``<id>.json`` manifest carrying its detection parameters
— and the manifest is what :func:`pymicro_wakeword.MicroWakeWord.from_config`
loads. The catalog of downloadable models lives in
:mod:`ubo_app.engines.microwakeword_catalog`.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from abstraction.wake_word_recognition_mixin import WakeWordRecognitionMixin
from typing_extensions import override

from ubo_app.engines.microwakeword_catalog import MODELS_DIR
from ubo_app.logger import logger
from ubo_app.store.services.speech_recognition import WakeWordEngineName

if TYPE_CHECKING:
    from collections.abc import Sequence

    from abstraction.wake_word_recognition_mixin import WakeTrigger
    from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures

__all__ = [
    'MODELS_DIR',
    'MicroWakeWordEngine',
    'delete_model',
    'scan_models',
    'staging_paths',
]

class StagingPaths(NamedTuple):
    """Where the two halves of an in-flight download live before install."""

    directory: Path
    config: Path
    weights: Path


def staging_paths(model_id: str) -> StagingPaths:
    """Return the staging layout a download for *model_id* writes into.

    The pair is staged under its *final* names inside a hidden directory rather
    than as ``<name>.part`` siblings of the installed models. ``from_config``
    resolves the weights as ``<manifest's directory>/<manifest's "model" key>``,
    so a ``<id>.json.part`` manifest sends :func:`validate_model` looking for a
    ``<id>.tflite`` that isn't there yet — which fails every download.
    :func:`scan_models` globs the top level only, so the directory stays
    invisible while the download is in flight.
    """
    directory = MODELS_DIR / f'.{model_id}.part'
    return StagingPaths(
        directory=directory,
        config=directory / f'{model_id}.json',
        weights=directory / f'{model_id}.tflite',
    )


def _load_model(config_path: Path) -> MicroWakeWord:
    """Load one model from its JSON manifest.

    ``from_config`` prints the parsed manifest to stdout (an upstream debug
    leftover); swallow it so it doesn't pollute the service log.
    """
    from pymicro_wakeword import MicroWakeWord

    with contextlib.redirect_stdout(io.StringIO()):
        return MicroWakeWord.from_config(config_path)


def scan_models() -> list[str]:
    """Return the loadable model ids on disk, sorted.

    A model is only listed when *both* halves of the pair are present, so every
    id the UI shows is actually loadable — the same guarantee
    ``openwakeword_engine.scan_models`` gets by globbing a single format.
    """
    if not MODELS_DIR.exists():
        return []
    return sorted(
        path.stem
        for path in MODELS_DIR.glob('*.json')
        if path.with_suffix('.tflite').exists()
    )


def validate_model(config_path: Path) -> bool:
    """Whether the model at *config_path* actually loads.

    Runs the real ``from_config`` path (which loads the paired ``.tflite`` into
    a TFLite interpreter) and releases it again. Cheap — these models are under
    100 KB — and catches a truncated or corrupted download that
    :func:`scan_models` would otherwise happily list.

    The weights are resolved by ``from_config`` as ``config_path.parent /
    config['model']``, *not* from ``config_path``'s own stem. A missing sibling
    is checked here rather than left to ``from_config``: upstream's loader
    dereferences the null interpreter that a failed open produces, which
    segfaults instead of raising, so ``except Exception`` below can't catch it.
    """
    try:
        weights = config_path.parent / json.loads(config_path.read_text())['model']
    except (OSError, ValueError, KeyError):
        logger.exception(
            'Unreadable microWakeWord manifest',
            extra={'path': config_path},
        )
        return False
    if not weights.is_file():
        logger.error(
            'microWakeWord manifest points at missing weights',
            extra={'path': config_path, 'weights': weights},
        )
        return False
    try:
        model = _load_model(config_path)
    except Exception:
        logger.exception(
            'Not a valid microWakeWord model',
            extra={'path': config_path},
        )
        return False
    model.close()
    return True


def delete_model(model_id: str) -> None:
    """Delete the file pair for *model_id* from disk.

    ``model_id`` may arrive from a remote (gRPC-dispatched) action, so it is
    treated as untrusted: anything that isn't a bare filename living directly in
    :data:`MODELS_DIR` (path separators, ``..``, absolute paths) is rejected
    before any filesystem operation, so a crafted id can't unlink files
    elsewhere. Unlike OpenWakeWord there are no shared helper models to refuse —
    every microWakeWord model is self-contained.
    """
    if not model_id or Path(model_id).name != model_id:
        logger.warning(
            'Refusing to delete model with invalid id',
            extra={'model_id': model_id},
        )
        return
    base = MODELS_DIR.resolve()
    for suffix in ('.json', '.tflite'):
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
                'Failed to delete microWakeWord model',
                extra={'path': path},
            )


class MicroWakeWordEngine(WakeWordRecognitionMixin):
    """microWakeWord wake-word detection engine."""

    def __init__(self) -> None:
        """Initialize the microWakeWord engine."""
        self._features: MicroWakeWordFeatures | None = None
        self._models: dict[str, MicroWakeWord] = {}
        # Maps of enabled model id -> trigger id and -> sensitivity, plus the
        # signature of the currently-loaded model set (so we only rebuild on
        # change).
        self._id_to_trigger: dict[str, str] = {}
        self._id_to_sensitivity: dict[str, float] = {}
        self._loaded_signature: tuple[str, ...] | None = None
        super().__init__(label='microWakeWord')

    @property
    @override
    def name(self) -> str:
        return WakeWordEngineName.MICROWAKEWORD

    @property
    @override
    def label(self) -> str:
        return 'microWakeWord'

    @override
    def set_triggers(self, triggers: Sequence[WakeTrigger] | None) -> None:
        """Set the triggers and (re)load only the enabled models on change."""
        super().set_triggers(triggers)
        self._id_to_trigger = {trigger.value: trigger.id for trigger in self.triggers}
        self._id_to_sensitivity = {
            trigger.value: trigger.sensitivity for trigger in self.triggers
        }
        # Signature reflects the requested models that actually exist on disk,
        # not just the requested set: a model whose files arrive later (e.g.
        # finishes downloading) changes the signature and triggers a reload,
        # instead of the signature committing to a set that ``_load_models``
        # only partially loaded. Sensitivity is part of it too — it maps onto
        # each model's ``probability_cutoff``, which is fixed at load time.
        signature = tuple(
            sorted(
                f'{model_id}@{self._id_to_sensitivity[model_id]}'
                for model_id in self._id_to_trigger
                if (MODELS_DIR / f'{model_id}.json').exists()
            ),
        )
        if signature == self._loaded_signature:
            return
        self._unload_models()
        if not signature:
            # No enabled models — nothing to load, treat as a committed empty
            # state.
            self._loaded_signature = signature
            return
        try:
            self._load_models()
        except (ImportError, RuntimeError):
            # Leave the signature uncommitted so a later sync (e.g. once the
            # model is downloaded) retries the load instead of short-circuiting.
            self._loaded_signature = None
            logger.exception(
                'Failed to load microWakeWord models',
                extra={'models_dir': MODELS_DIR},
            )
        else:
            self._loaded_signature = signature

    def _unload_models(self) -> None:
        """Release the loaded models' native TFLite interpreters.

        Each :class:`MicroWakeWord` owns a ``TfLiteInterpreter`` allocated
        outside Python's heap; dropping the reference without ``close()`` leaks
        it until the (non-deterministic) finalizer runs. Called on every reload,
        so a user toggling triggers doesn't accumulate interpreters.
        """
        for model in self._models.values():
            with contextlib.suppress(Exception):
                model.close()
        self._models = {}
        self._features = None

    def _load_models(self) -> None:
        """Load the enabled models from :data:`MODELS_DIR`.

        Raises:
            ImportError: If the ``pymicro_wakeword`` package is not installed.
            RuntimeError: If no enabled model could be loaded.

        """
        try:
            from pymicro_wakeword import MicroWakeWordFeatures
        except ImportError as error:
            msg = 'pymicro-wakeword package not installed'
            logger.exception(msg)
            raise ImportError(msg) from error

        models: dict[str, MicroWakeWord] = {}
        for model_id in self._id_to_trigger:
            config_path = MODELS_DIR / f'{model_id}.json'
            if not config_path.exists():
                continue
            try:
                model = _load_model(config_path)
            except Exception:
                logger.exception(
                    'Failed to load microWakeWord model',
                    extra={'model': model_id},
                )
                continue
            # Per-model activation: higher sensitivity → lower required
            # confidence, the same mapping OpenWakeWord uses. Overrides the
            # manifest's upstream-tuned cutoff, which the menu seeds the
            # trigger's sensitivity from so the default round-trips.
            model.probability_cutoff = 1 - self._id_to_sensitivity[model_id]
            models[model_id] = model

        if not models:
            msg = f'No enabled microWakeWord models could be loaded from {MODELS_DIR}'
            raise RuntimeError(msg)

        # One frontend shared across every model — they all consume the same
        # feature frames, so computing them once is the whole point of the
        # streaming design.
        self._features = MicroWakeWordFeatures()
        self._models = models
        logger.info(
            'microWakeWord models loaded',
            extra={'models': list(models)},
        )

    def _detect(self, chunk: bytes) -> list[str]:
        """Run the frontend + every model over *chunk*, returning fired trigger ids.

        Synchronous and CPU-bound — call it off the event loop.
        """
        if self._features is None:
            return []
        fired: list[str] = []
        for frame in self._features.process_streaming(chunk):
            for model_id, model in self._models.items():
                if not model.process_streaming(frame):
                    continue
                trigger_id = self._id_to_trigger.get(model_id)
                if trigger_id is None:
                    continue
                logger.info(
                    'microWakeWord detected wake word',
                    extra={
                        'model': model_id,
                        'sensitivity': self._id_to_sensitivity[model_id],
                    },
                )
                fired.append(trigger_id)
                # The sliding-window mean stays above the cutoff for several
                # frames after an activation, so without this the same
                # utterance fires repeatedly. ``reset`` clears the window and
                # reloads the model to drop its streaming state.
                model.reset()
        return fired

    @override
    async def _run(self) -> None:
        """Consume mic audio and push detected wake words onto the queue."""
        while self.should_be_running():
            chunk = await self.input_queue.get()
            if self._features is None:
                # No model yet (not downloaded / failed to load). Drop audio and
                # keep the loop alive so a runtime download self-heals.
                continue
            for trigger_id in await asyncio.to_thread(self._detect, chunk):
                await self.woke_word_recognitions_queue.put(trigger_id)
