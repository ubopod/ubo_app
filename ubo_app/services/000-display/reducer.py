# ruff: noqa: D100, D103
from __future__ import annotations

import datetime
from dataclasses import replace

from redux import (
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.logger import logger
from ubo_app.store.services.display import (
    DisplayAction,
    DisplayBlankAction,
    DisplayBlankEvent,
    DisplayPauseAction,
    DisplayRedrawAction,
    DisplayRedrawEvent,
    DisplayResumeAction,
    DisplayState,
    DisplayUnblankAction,
    DisplayUnblankEvent,
    DisplayUpdateActivityAction,
)

Action = InitAction | DisplayAction


def reducer(
    state: DisplayState | None,
    action: Action,
) -> ReducerResult[
    DisplayState,
    None,
    DisplayRedrawEvent | DisplayBlankEvent | DisplayUnblankEvent,
]:
    if state is None:
        if isinstance(action, InitAction):
            logger.info('Display reducer initialized')
            return DisplayState()
        raise InitializationActionError(action)

    # Log all display actions
    if isinstance(action, DisplayAction):
        logger.debug(
            'Display reducer received action',
            extra={'action_type': type(action).__name__},
        )

    match action:
        case DisplayPauseAction():
            return replace(state, is_paused=True)

        case DisplayResumeAction():
            return CompleteReducerResult(
                state=replace(state, is_paused=False),
                events=[DisplayRedrawEvent()],
            )

        case DisplayRedrawAction():
            return CompleteReducerResult(
                state=state,
                events=[DisplayRedrawEvent()],
            )

        case DisplayBlankAction():
            logger.info('DisplayBlankAction received in reducer')
            return CompleteReducerResult(
                state=replace(state, is_blanked=True),
                events=[DisplayBlankEvent()],
            )

        case DisplayUnblankAction():
            logger.info('DisplayUnblankAction received in reducer')
            return CompleteReducerResult(
                state=replace(
                    state,
                    is_blanked=False,
                    last_activity_time=datetime.datetime.now(tz=datetime.UTC).timestamp(),
                ),
                events=[DisplayUnblankEvent(), DisplayRedrawEvent()],
            )

        case DisplayUpdateActivityAction():
            timestamp = datetime.datetime.now(tz=datetime.UTC).timestamp()
            logger.debug(
                'DisplayUpdateActivityAction received',
                extra={'timestamp': timestamp},
            )
            return replace(state, last_activity_time=timestamp)

        case _:
            return state
