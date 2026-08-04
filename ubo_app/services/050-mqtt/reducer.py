"""MQTT bridge reducer."""

from __future__ import annotations

from dataclasses import replace

from redux import (
    BaseEvent,
    CompleteReducerResult,
    InitAction,
    InitializationActionError,
    ReducerResult,
)

from ubo_app.store.services.mqtt import (
    MqttAction,
    MqttAnnounceRequestedEvent,
    MqttBundledCredentialsChangedAction,
    MqttConnectionStatus,
    MqttPublishAction,
    MqttPublishEvent,
    MqttRequestAnnounceAction,
    MqttSetAllowRemoteControlAction,
    MqttSetBrokerAction,
    MqttSetBundledExposeToLanAction,
    MqttSetEnabledAction,
    MqttSetPublishedComponentsAction,
    MqttSetStatusAction,
    MqttState,
)

Action = InitAction | MqttAction


def reducer(
    state: MqttState | None,
    action: Action,
) -> ReducerResult[MqttState, Action, BaseEvent]:
    """MQTT bridge reducer."""
    if state is None:
        if isinstance(action, InitAction):
            return MqttState()
        raise InitializationActionError(action)

    match action:
        case MqttSetStatusAction():
            return replace(
                state,
                status=action.status,
                last_error=action.error
                if action.status is MqttConnectionStatus.ERROR
                else None,
            )
        case MqttSetBrokerAction():
            return replace(state, broker=action.broker)
        case MqttSetEnabledAction():
            return replace(state, is_enabled=action.is_enabled)
        case MqttSetAllowRemoteControlAction():
            return replace(state, allow_remote_control=action.allow_remote_control)
        case MqttSetBundledExposeToLanAction():
            return replace(state, bundled_expose_to_lan=action.expose_to_lan)
        case MqttBundledCredentialsChangedAction():
            return replace(
                state,
                bundled_credentials_revision=state.bundled_credentials_revision + 1,
            )
        case MqttSetPublishedComponentsAction():
            return replace(
                state,
                published_components=action.published_components,
            )
        # The two below are transparent: they carry no state, they exist so a
        # producer in another service can reach the bridge through the store.
        case MqttPublishAction():
            return CompleteReducerResult(
                state=state,
                events=[
                    MqttPublishEvent(
                        channel=action.channel,
                        payload=action.payload,
                        retain=action.retain,
                        qos=action.qos,
                    ),
                ],
            )
        case MqttRequestAnnounceAction():
            return CompleteReducerResult(
                state=state,
                events=[MqttAnnounceRequestedEvent()],
            )
        case _:
            return state
