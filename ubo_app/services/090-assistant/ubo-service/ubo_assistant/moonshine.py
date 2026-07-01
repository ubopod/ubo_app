"""Moonshine speech-to-text service for pipecat.

Moonshine's pipecat service downloads its model the first time the underlying
``MoonshineSTTService`` is built and exposes no local-path parameter, so there
is no core-side download. ``MoonshineSTTProxy`` is a stable switcher member that
owns a swappable underlying ``MoonshineSTTService`` and separates two concerns:

* **Selection** (``set_active_model``) only loads a model the pipeline should
  use, and only when it's *already downloaded* — so boot-time selection never
  triggers a surprise download.
* **Download** (``download_model``) is an explicit, user-initiated action: it
  builds the model (downloading it), reports a spinner + the downloaded id back
  to the core, and swaps it in if it's the active model.
* **Delete** (``delete_model``) removes the cached files and reports the removal.

Builds run off the event loop; the requested model is reconciled after every
build so an in-flight download followed by a new selection can't strand the
proxy on a stale model.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    StartFrame,
    SystemFrame,
)
from pipecat.services.moonshine.stt import MoonshineSTTService
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import STTService
from ubo_bindings.ubo.v1 import (
    Action,
    AssistantAddMoonshineDownloadedModelAction,
    AssistantRemoveMoonshineDownloadedModelAction,
    AssistantSetMoonshineDownloadingAction,
)

from ubo_assistant.moonshine_cache import remove_model

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Coroutine, Iterable

    from pipecat.processors.frame_processor import (
        FrameDirection,
        FrameProcessorSetup,
    )
    from ubo_bindings.client import UboRPCClient

DEFAULT_MOONSHINE_MODEL_ID = 'tiny'


class MoonshineSTTProxy(STTService):
    """Switcher branch wrapping a model-swappable Moonshine STT service.

    Pipecat freezes its switcher service list at ``__init__``, so this proxy is
    registered once and the real :class:`MoonshineSTTService` is built lazily.
    Frames are forwarded to the current underlying service, mirroring
    ``GenericSTTProxy``.
    """

    def __init__(
        self,
        client: UboRPCClient,
        *,
        model_id: str = DEFAULT_MOONSHINE_MODEL_ID,
    ) -> None:
        """Initialize the proxy with no underlying service yet."""
        super().__init__(settings=STTSettings(model=model_id, language=None))
        self.client = client
        self._service: MoonshineSTTService | None = None
        self._processor_setup: FrameProcessorSetup | None = None
        self._start_frame: StartFrame | None = None
        self._build_executor = ThreadPoolExecutor(max_workers=1)
        # ``_active_model_id`` is the model the live pipeline should use (set by
        # the selection autorun). ``_loaded_model_id`` is what's built into
        # ``_service``. ``_downloaded`` is the set known to be on disk (seeded
        # from the persisted store and updated on download/delete).
        self._active_model_id = model_id
        self._loaded_model_id: str | None = None
        self._downloaded: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()

    @property
    def service(self) -> MoonshineSTTService | None:
        """Current underlying Moonshine STT service."""
        return self._service

    async def setup(self, setup: FrameProcessorSetup) -> None:
        """Set up the proxy, capture the loop, and reconcile the active model."""
        await super().setup(setup)
        self._processor_setup = setup
        self._loop = asyncio.get_running_loop()
        if self._service is not None:
            await self._service.setup(setup)
        # Selection/downloaded autoruns may have fired before the loop existed;
        # reconcile now that we can load from cache.
        self.create_task(self._ensure_active())

    async def cleanup(self) -> None:
        """Clean up the current underlying STT, if any."""
        if self._service is not None:
            await self._service.cleanup()
        await super().cleanup()

    # -- foreign-thread entry points (autorun / event callbacks) -----------

    def set_active_model(self, model_id: str) -> None:
        """Record the model the live pipeline should use (no download)."""
        if not model_id or model_id == self._active_model_id:
            return
        self._active_model_id = model_id
        self._run_on_loop(self._ensure_active())

    def set_downloaded(self, model_ids: Iterable[str]) -> None:
        """Seed/refresh the set of models known to be on disk."""
        self._downloaded = set(model_ids)
        self._run_on_loop(self._ensure_active())

    def download_model(self, model_id: str) -> None:
        """Explicitly download *model_id* (builds it, reporting progress)."""
        if not model_id:
            return
        self._run_on_loop(self._download(model_id))

    def delete_model(self, model_id: str) -> None:
        """Delete *model_id*'s cached files and report the removal."""
        if not model_id:
            return
        self._run_on_loop(self._delete(model_id))

    def _run_on_loop(self, coro: Coroutine[object, object, None]) -> None:
        loop = self._loop
        if loop is None:
            # Not set up yet — ``setup`` reconciles the active model, and
            # download/delete only arrive from post-boot user actions.
            coro.close()
            return
        loop.call_soon_threadsafe(self.create_task, coro)

    # -- reconciliation (run on the pipeline loop) -------------------------

    async def _ensure_active_locked(self) -> None:
        """Load the active model from cache if downloaded. Assumes lock held."""
        while (
            self._active_model_id != self._loaded_model_id
            and self._active_model_id in self._downloaded
        ):
            target = self._active_model_id
            service = await self._build(target)
            if service is None:
                return
            if target != self._active_model_id:
                # Selection changed mid-build — drop this one and re-evaluate.
                await service.cleanup()
                continue
            await self._swap(service)
            self._loaded_model_id = target

    async def _ensure_active(self) -> None:
        async with self._lock:
            await self._ensure_active_locked()

    async def _download(self, model_id: str) -> None:
        async with self._lock:
            self._dispatch_downloading(model_id)
            try:
                service = await self._build(model_id)
                if service is None:
                    return
                if model_id not in self._downloaded:
                    self._downloaded.add(model_id)
                    self._dispatch_added(model_id)
                if (
                    model_id == self._active_model_id
                    and model_id != self._loaded_model_id
                ):
                    await self._swap(service)
                    self._loaded_model_id = model_id
                else:
                    # Built only to fetch the files — not the active model.
                    await service.cleanup()
            finally:
                self._dispatch_downloading('')
            # The active model may have changed during the download.
            await self._ensure_active_locked()

    async def _delete(self, model_id: str) -> None:
        async with self._lock:
            await asyncio.to_thread(remove_model, model_id)
            self._downloaded.discard(model_id)
            self._dispatch_removed(model_id)
            if model_id == self._loaded_model_id:
                if self._service is not None:
                    await self._service.cleanup()
                self._service = None
                self._loaded_model_id = None

    async def _build(self, model_id: str) -> MoonshineSTTService | None:
        try:
            return await asyncio.get_running_loop().run_in_executor(
                self._build_executor,
                lambda: MoonshineSTTService(
                    settings=MoonshineSTTService.Settings(model=model_id),
                ),
            )
        except Exception:
            logger.exception(
                'Failed to build Moonshine model',
                extra={'model_id': model_id},
            )
            return None

    async def _swap(self, service: MoonshineSTTService) -> None:
        """Replace the underlying service, replaying setup + StartFrame."""
        if self._service is not None:
            await self._service.cleanup()
        self._service = service
        service.push_frame = self.push_frame
        if self._processor_setup is not None:
            await service.setup(self._processor_setup)
        if self._start_frame is not None:
            await service.queue_frame(self._start_frame)

    # -- frame plumbing ----------------------------------------------------

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Stub — frames are routed through ``queue_frame`` on the underlying."""
        _ = audio
        yield None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Forward frames to the current underlying STT when configured.

        Note: a ``StartFrame`` is only captured/forwarded — it never triggers a
        build, so merely starting the pipeline can't auto-download a model.
        """
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self._start_frame = frame
        if self._service is not None:
            await self._service.queue_frame(frame, direction)
        elif isinstance(frame, SystemFrame):
            await self.push_frame(frame, direction)

    # -- gRPC reporting ----------------------------------------------------

    def _dispatch_downloading(self, model_id: str) -> None:
        self.client.dispatch(
            action=Action(
                assistant_set_moonshine_downloading_action=(
                    AssistantSetMoonshineDownloadingAction(model_id=model_id)
                ),
            ),
        )

    def _dispatch_added(self, model_id: str) -> None:
        self.client.dispatch(
            action=Action(
                assistant_add_moonshine_downloaded_model_action=(
                    AssistantAddMoonshineDownloadedModelAction(model_id=model_id)
                ),
            ),
        )

    def _dispatch_removed(self, model_id: str) -> None:
        self.client.dispatch(
            action=Action(
                assistant_remove_moonshine_downloaded_model_action=(
                    AssistantRemoveMoonshineDownloadedModelAction(model_id=model_id)
                ),
            ),
        )
