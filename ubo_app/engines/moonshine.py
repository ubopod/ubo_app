"""Moonshine engine interface.

Thin counterpart to :mod:`ubo_app.engines.vosk`. Moonshine's model download is
owned by the assistant *subprocess* (pipecat's ``MoonshineSTTService`` downloads
into its local cache on first use), so this engine holds no download/extract
logic. It only surfaces the engine in the Manage menu and reports setup state:
the model is "set up" once the subprocess has reported it as downloaded via
``AssistantSetMoonshineDownloadedModelsAction``. Selecting a model dispatches
``AssistantSetSelectedMoonshineModelAction``, which the subprocess picks up over
a gRPC autorun and downloads.
"""

from __future__ import annotations

from typing_extensions import override

from ubo_app.engines.abstraction.ai_provider_mixin import AIProviderMixin
from ubo_app.engines.abstraction.needs_setup_mixin import NeedsSetupMixin
from ubo_app.engines.moonshine_catalog import DEFAULT_MOONSHINE_MODEL_ID
from ubo_app.store.main import store
from ubo_app.store.services.assistant import (
    AssistantDownloadMoonshineModelAction,
    AssistantSetSelectedMoonshineModelAction,
)


@store.with_state(lambda state: state.assistant.selected_moonshine_model)
def _read_selected_model(selected_model: str) -> str:
    """Read the user's currently selected Moonshine model id from the store."""
    return selected_model or DEFAULT_MOONSHINE_MODEL_ID


class MoonshineEngine(NeedsSetupMixin, AIProviderMixin):
    """Moonshine engine."""

    @property
    def name(self) -> str:
        """The internal name of the Moonshine engine."""
        return 'moonshine'

    @property
    def label(self) -> str:
        """The display label for the Moonshine engine."""
        return 'Moonshine'

    @property
    def not_setup_message(self) -> str:
        """Message shown when the selected Moonshine model isn't downloaded."""
        return 'Moonshine model not downloaded. Pick a model in Settings to fetch it.'

    @property
    @override
    @store.with_state(
        lambda state: (
            state.assistant.selected_moonshine_model,
            state.assistant.moonshine_downloaded_models,
        ),
    )
    def is_setup(  # noqa: PLR0206
        self,
        data: tuple[str, tuple[str, ...]],
    ) -> bool:
        """Return True iff the currently selected Moonshine model is downloaded."""
        selected_model, downloaded_models = data
        model_id = selected_model or DEFAULT_MOONSHINE_MODEL_ID
        return model_id in downloaded_models

    @override
    async def _setup(self) -> None:
        if self.is_setup:
            return

        # Explicitly select *and* request a download. The download is a separate
        # action from selection (selection alone never downloads), so tapping
        # Set Up always fetches the model — even when it's already the selected
        # one. The subprocess reports the spinner + downloaded set back to core.
        model_id = _read_selected_model()
        store.dispatch(
            AssistantSetSelectedMoonshineModelAction(model_id=model_id),
            AssistantDownloadMoonshineModelAction(model_id=model_id),
        )
