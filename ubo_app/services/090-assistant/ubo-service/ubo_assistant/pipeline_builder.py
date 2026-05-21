"""Builder for one-shot programmatic request pipelines.

Assembles a short-lived pipecat ``Pipeline`` for a contiguous sub-chain of the
STT → LLM → TTS stages. Unlike the live mic→speaker pipeline (built in ``main.py``)
a request pipeline has no input transport — frames are queued onto the task — no
VAD / barge-in / turn-detection processors, and no image-generation branch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask

if TYPE_CHECKING:
    from pipecat.frames.frames import Frame
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
    )
    from pipecat.processors.frame_processor import FrameProcessor

STT = 'stt'
LLM = 'llm'
TTS = 'tts'
STAGE_ORDER: tuple[str, ...] = (STT, LLM, TTS)


def validate_stage_chain(stages: list[str]) -> None:
    """Raise ``ValueError`` unless ``stages`` is a contiguous sub-chain of STAGE_ORDER.

    Valid: ``[stt]``, ``[llm]``, ``[tts]``, ``[stt, llm]``, ``[llm, tts]``,
    ``[stt, llm, tts]``. Invalid: gaps (``[stt, tts]``), wrong order, duplicates,
    empty.
    """
    if not stages:
        msg = 'Pipeline stages must not be empty'
        raise ValueError(msg)
    try:
        indices = [STAGE_ORDER.index(stage) for stage in stages]
    except ValueError as exception:
        msg = f'Unknown pipeline stage in {stages}; valid stages: {STAGE_ORDER}'
        raise ValueError(msg) from exception
    if indices != list(range(indices[0], indices[0] + len(indices))):
        msg = (
            f'Pipeline stages must be a contiguous sub-chain of {STAGE_ORDER}, '
            f'got {stages}'
        )
        raise ValueError(msg)


def build_request_pipeline(  # noqa: PLR0913
    *,
    stages: list[str],
    stage_services: dict[str, FrameProcessor],
    collector: FrameProcessor,
    context_aggregator: LLMContextAggregatorPair | None = None,
    audio_in_sample_rate: int = 16000,
    idle_timeout_secs: float = 120.0,
    idle_timeout_frames: tuple[type[Frame], ...] | None = None,
) -> tuple[PipelineTask, PipelineRunner]:
    """Assemble a request pipeline, task and runner for a contiguous STT/LLM/TTS chain.

    Args:
        stages: Contiguous sub-chain of ``STAGE_ORDER`` (validated).
        stage_services: Maps each requested stage to its single provider processor.
        collector: Terminal processor — a ``GRPCTerminalCollector``.
        context_aggregator: Required when the LLM stage is present; its ``user()`` and
            ``assistant()`` processors are placed around the LLM.
        audio_in_sample_rate: Input audio sample rate for ``PipelineParams``.
        idle_timeout_secs: The task is cancelled after this many seconds without an
            ``idle_timeout_frames`` frame — bounds a hung provider.
        idle_timeout_frames: Frame types whose arrival resets the idle timer.

    Returns:
        A ``(PipelineTask, PipelineRunner)`` pair ready to run.

    """
    validate_stage_chain(stages)

    inner: list[FrameProcessor] = []
    assistant_aggregator: FrameProcessor | None = None

    if STT in stages:
        inner.append(stage_services[STT])

    if LLM in stages:
        if context_aggregator is None:
            msg = 'context_aggregator is required when the LLM stage is present'
            raise ValueError(msg)
        inner.append(context_aggregator.user())
        inner.append(stage_services[LLM])
        assistant_aggregator = context_aggregator.assistant()

    if TTS in stages:
        inner.append(stage_services[TTS])

    processors: list[FrameProcessor] = [*inner, collector]
    if assistant_aggregator is not None:
        processors.append(assistant_aggregator)

    pipeline = Pipeline(processors)
    params = PipelineParams(audio_in_sample_rate=audio_in_sample_rate)

    if idle_timeout_frames is None:
        task = PipelineTask(
            pipeline,
            params=params,
            cancel_on_idle_timeout=True,
            idle_timeout_secs=idle_timeout_secs,
        )
    else:
        task = PipelineTask(
            pipeline,
            params=params,
            cancel_on_idle_timeout=True,
            idle_timeout_secs=idle_timeout_secs,
            idle_timeout_frames=idle_timeout_frames,
        )

    runner = PipelineRunner(handle_sigint=False)
    return task, runner
