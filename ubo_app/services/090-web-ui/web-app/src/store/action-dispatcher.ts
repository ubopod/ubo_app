import type { ClientReadableStream } from "grpc-web";

import {
  DispatchActionRequest,
  DispatchActionResponse,
} from "../bindings/store/v1/store_pb";
import { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import {
  Action,
  AssistantStartListeningAction,
  AssistantStopListeningAction,
  AudioChangeVolumeAction,
  AudioDevice,
  AudioReportSampleAction,
  AudioSetMuteStatusAction,
  AudioSetVolumeAction,
  AudioToggleMuteStatusAction,
  ExecuteMenuActionAction,
  MenuChooseByIndexAction,
  MenuScrollAction,
  MenuScrollDirection,
  NotificationsClearByIdAction,
  PowerOffAction,
  RebootAction,
  StackPopAction,
  StackPopToRootAction,
  StackPushMenuAction,
} from "../bindings/ubo/v1/ubo_pb";

// Identifies this browser session as a mic source so the core only feeds the
// assistant audio from the source that started listening. Generated once per
// page load (distinct tabs ⇒ distinct ids). Not using crypto.randomUUID() since
// the device serves plain HTTP, a non-secure context where it's unavailable.
const AUDIO_SOURCE = `web-ui:${Date.now().toString(36)}-${Math.random()
  .toString(36)
  .slice(2)}`;

// Browsers limit concurrent HTTP/1.1 connections per origin to 6.
// gRPC-web streaming subscriptions (view, stack, metrics, audio×2) use 5 slots.
// Page-specific streams (e.g. camera viewfinder) use the 6th slot, leaving none
// for dispatch requests. Registering page streams here lets dispatch() cancel
// them before sending, freeing a connection slot.
const pageStreams = new Set<() => void>();

export function registerPageStream(cancel: () => void): () => void {
  pageStreams.add(cancel);
  return () => pageStreams.delete(cancel);
}

// Post-dispatch listeners — called after every action dispatch so consumers
// (e.g. status polling) can refresh immediately instead of waiting for the
// next polling interval.
const postDispatchListeners = new Set<() => void>();

export function onPostDispatch(listener: () => void): () => void {
  postDispatchListeners.add(listener);
  return () => postDispatchListeners.delete(listener);
}

export function triggerPostDispatch(): void {
  for (const listener of postDispatchListeners) {
    listener();
  }
}

// In-flight audio-sample dispatches. Audio is reported as ~50 unary
// DispatchAction RPCs/sec, which can saturate the browser's limited HTTP/1.1
// connection pool and starve latency-sensitive control actions (e.g. stop
// listening, navigation). Tracking these lets a control dispatch abort the
// buffered audio and reclaim a connection slot so it isn't queued behind them.
const pendingAudioCalls = new Set<ClientReadableStream<DispatchActionResponse>>();

export function cancelPendingAudioSamples(): void {
  for (const call of pendingAudioCalls) {
    call.cancel();
  }
  pendingAudioCalls.clear();
}

function dispatch(store: StoreServiceClient, action: Action): void {
  // Cancel page-specific streams to free connection slots for this request
  for (const cancel of pageStreams) {
    cancel();
  }
  pageStreams.clear();

  // Control actions take priority over buffered mic audio: abort any in-flight
  // audio-sample RPCs so this dispatch gets a connection slot immediately.
  cancelPendingAudioSamples();

  const request = new DispatchActionRequest();
  request.setAction(action);
  store.dispatchAction(request, null).then(() => triggerPostDispatch());
}

export function chooseByIndex(
  store: StoreServiceClient,
  index: number,
): void {
  const choose = new MenuChooseByIndexAction();
  choose.setIndex(index);
  const action = new Action();
  action.setMenuChooseByIndexAction(choose);
  dispatch(store, action);
}

export function executeAction(
  store: StoreServiceClient,
  actionId: string,
  menuKey?: string,
): void {
  const executeAction = new ExecuteMenuActionAction();
  executeAction.setActionId(actionId);
  if (menuKey) {
    executeAction.setMenuKey(menuKey);
  }
  const action = new Action();
  action.setExecuteMenuActionAction(executeAction);
  dispatch(store, action);
}

export function dismissNotification(
  store: StoreServiceClient,
  notificationId: string,
): void {
  goBack(store);
  const clearById = new NotificationsClearByIdAction();
  clearById.setId(notificationId);
  const action = new Action();
  action.setNotificationsClearByIdAction(clearById);
  dispatch(store, action);
}

export function goBack(store: StoreServiceClient, count = 1): void {
  const stackPop = new StackPopAction();
  stackPop.setCount(count);
  const action = new Action();
  action.setStackPopAction(stackPop);
  dispatch(store, action);
}

export function goHome(store: StoreServiceClient): void {
  const stackPopToRoot = new StackPopToRootAction();
  const action = new Action();
  action.setStackPopToRootAction(stackPopToRoot);
  dispatch(store, action);
}

export function navigateTo(
  store: StoreServiceClient,
  menuKey: string,
): void {
  const stackPush = new StackPushMenuAction();
  stackPush.setMenuKey(menuKey);
  const action = new Action();
  action.setStackPushMenuAction(stackPush);
  dispatch(store, action);
}

export function scroll(
  store: StoreServiceClient,
  direction: "up" | "down",
): void {
  const menuScroll = new MenuScrollAction();
  menuScroll.setDirection(
    direction === "up"
      ? MenuScrollDirection.MENU_SCROLL_DIRECTION_UP
      : MenuScrollDirection.MENU_SCROLL_DIRECTION_DOWN,
  );
  const action = new Action();
  action.setMenuScrollAction(menuScroll);
  dispatch(store, action);
}

export function powerOff(store: StoreServiceClient): void {
  const powerOffAction = new PowerOffAction();
  const action = new Action();
  action.setPowerOffAction(powerOffAction);
  dispatch(store, action);
}

export function reboot(store: StoreServiceClient): void {
  const rebootAction = new RebootAction();
  const action = new Action();
  action.setRebootAction(rebootAction);
  dispatch(store, action);
}

export function startListening(store: StoreServiceClient): void {
  const startAction = new AssistantStartListeningAction();
  startAction.setAudioSource(AUDIO_SOURCE);
  const action = new Action();
  action.setAssistantStartListeningAction(startAction);
  dispatch(store, action);
}

export function stopListening(store: StoreServiceClient): void {
  const stopAction = new AssistantStopListeningAction();
  const action = new Action();
  action.setAssistantStopListeningAction(stopAction);
  dispatch(store, action);
}

export function reportAudioSample(
  store: StoreServiceClient,
  pcm16: Uint8Array,
  timestamp: number,
): void {
  const reportAction = new AudioReportSampleAction();
  reportAction.setSampleSpeechRecognition(pcm16);
  reportAction.setTimestamp(timestamp);
  reportAction.setAudioSource(AUDIO_SOURCE);
  const action = new Action();
  action.setAudioReportSampleAction(reportAction);

  const request = new DispatchActionRequest();
  request.setAction(action);
  // Use the cancelable (callback) form rather than dispatch(): audio is a
  // fire-and-forget data stream (a dropped trailing sample on stop is
  // harmless), and a control dispatch must be able to abort these in-flight
  // calls. Going through dispatch() would also cancel page streams 50x/sec.
  const call: ClientReadableStream<DispatchActionResponse> =
    store.dispatchAction(request, null, () => {
      pendingAudioCalls.delete(call);
    });
  pendingAudioCalls.add(call);
}

export function setMicMute(
  store: StoreServiceClient,
  mute: boolean,
): void {
  const muteAction = new AudioSetMuteStatusAction();
  muteAction.setDevice(AudioDevice.AUDIO_DEVICE_INPUT);
  muteAction.setIsMute(mute);
  const action = new Action();
  action.setAudioSetMuteStatusAction(muteAction);
  dispatch(store, action);
}

export function toggleMicMute(store: StoreServiceClient): void {
  const toggleAction = new AudioToggleMuteStatusAction();
  toggleAction.setDevice(AudioDevice.AUDIO_DEVICE_INPUT);
  const action = new Action();
  action.setAudioToggleMuteStatusAction(toggleAction);
  dispatch(store, action);
}

export function changeVolume(
  store: StoreServiceClient,
  amount: number,
): void {
  const changeAction = new AudioChangeVolumeAction();
  changeAction.setAmount(amount);
  changeAction.setDevice(AudioDevice.AUDIO_DEVICE_OUTPUT);
  const action = new Action();
  action.setAudioChangeVolumeAction(changeAction);
  dispatch(store, action);
}

export function setVolume(store: StoreServiceClient, volume: number): void {
  const setAction = new AudioSetVolumeAction();
  setAction.setVolume(volume);
  setAction.setDevice(AudioDevice.AUDIO_DEVICE_OUTPUT);
  const action = new Action();
  action.setAudioSetVolumeAction(setAction);
  dispatch(store, action);
}
