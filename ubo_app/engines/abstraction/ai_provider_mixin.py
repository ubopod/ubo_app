"""Mixin for AI providers that require setup."""

from collections.abc import Sequence

from ubo_app.engines.abstraction.engine import EngineMixin


class AIProviderMixin(EngineMixin):
    """Base class for AI providers that require setup."""

    #: Hand-curated list of models the user can pick from in the GUI when this
    #: provider is selected. Subclasses (typically LLM engines) override with
    #: their preferred short-list. Empty tuple means "no model picker".
    CURATED_MODELS: tuple[str, ...] = ()

    async def list_models(self) -> Sequence[str]:
        """Return the model ids the user can pick from for this provider.

        Default returns ``CURATED_MODELS``. Engines that can fetch a live list
        from the provider (e.g. an OpenAI-compatible ``/models`` endpoint) may
        override this; on failure they should fall back to ``CURATED_MODELS``
        so the user always has *some* choices.
        """
        return self.CURATED_MODELS
