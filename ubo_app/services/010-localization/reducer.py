# ruff: noqa: D100, D103
from __future__ import annotations

from dataclasses import replace

from redux import CompleteReducerResult, InitAction, InitializationActionError

from ubo_app.store.services.localization import (
    LocalizationAction,
    LocalizationEvent,
    LocalizationLanguageChangedEvent,
    LocalizationSetLanguageAction,
    LocalizationState,
)


def reducer(
    state: LocalizationState | None,
    action: LocalizationAction,
) -> (
    LocalizationState
    | CompleteReducerResult[
        LocalizationState,
        LocalizationAction,
        LocalizationEvent,
    ]
):
    if state is None:
        if isinstance(action, InitAction):
            return LocalizationState()
        raise InitializationActionError(action)

    match action:
        case LocalizationSetLanguageAction():
            if state.language == action.language:
                return state
            return CompleteReducerResult(
                state=replace(state, language=action.language),
                events=[
                    LocalizationLanguageChangedEvent(language=action.language),
                ],
            )

        case _:
            return state
