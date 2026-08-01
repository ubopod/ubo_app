import { createContext, useContext } from "react";

import type { AppState } from "./types";
import {
  SubscribeEventRequest,
  SubscribeEventResponse,
  SubscribeStoreRequest,
  SubscribeStoreResponse,
} from "../bindings/store/v1/store_pb";
import { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import {
  Event,
  StackChangedEvent,
  ViewChangedEvent,
  WebUIInputCommand,
  WebUIInputEvent,
} from "../bindings/ubo/v1/ubo_pb";

// Maps a navigation command delivered over gRPC (e.g. from a bound IR remote
// key) to the DOM key the web UI's existing keyboard handlers already
// understand. Back → Backspace (goBack) and Home → Escape (goHome) are handled
// by useKeyboardNavigation; the arrows and Enter are handled by TileGrid.
const NAVIGATION_KEYS: Partial<Record<WebUIInputCommand, string>> = {
  [WebUIInputCommand.WEB_UI_INPUT_COMMAND_UP]: "ArrowUp",
  [WebUIInputCommand.WEB_UI_INPUT_COMMAND_DOWN]: "ArrowDown",
  [WebUIInputCommand.WEB_UI_INPUT_COMMAND_LEFT]: "ArrowLeft",
  [WebUIInputCommand.WEB_UI_INPUT_COMMAND_RIGHT]: "ArrowRight",
  [WebUIInputCommand.WEB_UI_INPUT_COMMAND_SELECT]: "Enter",
  [WebUIInputCommand.WEB_UI_INPUT_COMMAND_BACK]: "Backspace",
  [WebUIInputCommand.WEB_UI_INPUT_COMMAND_HOME]: "Escape",
};

function synthesizeNavigationKey(command: WebUIInputCommand): void {
  const key = NAVIGATION_KEYS[command];
  if (!key) return;

  // Dispatch on the focused tile when it lives inside the grid (so the event
  // bubbles to TileGrid's onKeyDown), otherwise on the grid itself, otherwise
  // on <body> so window-level handlers (Back/Home) still fire.
  const grid = document.querySelector<HTMLElement>("[data-tile-grid]");
  const active = document.activeElement;
  const target =
    grid && active instanceof HTMLElement && grid.contains(active)
      ? active
      : (grid ?? document.body);

  for (const type of ["keydown", "keyup"] as const) {
    target.dispatchEvent(
      new KeyboardEvent(type, { key, bubbles: true, cancelable: true }),
    );
  }
}

function decodeDoubleValue(bytes: Uint8Array): number {
  // DoubleValue protobuf: field 1 (tag 0x09 = field 1, wire type 1 = 64-bit)
  // followed by 8 bytes of IEEE 754 double
  if (bytes.length >= 9 && bytes[0] === 0x09) {
    const view = new DataView(bytes.buffer, bytes.byteOffset + 1, 8);
    return view.getFloat64(0, true); // little-endian
  }
  return 0;
}

export type StateListener = (state: AppState) => void;

export class StateManager {
  private state: AppState = {
    currentView: null,
    statusBar: null,
    stack: [],
    connected: false,
    cpuPercent: 0,
    ramPercent: 0,
    volume: 0,
  };

  private listeners: Set<StateListener> = new Set();
  private viewStackStream: ReturnType<
    StoreServiceClient["subscribeEvent"]
  > | null = null;
  private metricsStream: ReturnType<
    StoreServiceClient["subscribeStore"]
  > | null = null;

  constructor(private store: StoreServiceClient) {
    this.subscribeToViewAndStackChanges();
    this.subscribeToSystemMetrics();
  }

  getState(): AppState {
    return this.state;
  }

  subscribe(listener: StateListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }

  private update(partial: Partial<AppState>): void {
    this.state = { ...this.state, ...partial };
    this.notify();
  }

  private subscribeToViewAndStackChanges(): void {
    if (this.viewStackStream) {
      this.viewStackStream.cancel();
    }

    const request = new SubscribeEventRequest();
    const viewEvent = new Event();
    viewEvent.setViewChangedEvent(new ViewChangedEvent());
    request.addEvents(viewEvent);
    const stackEvent = new Event();
    stackEvent.setStackChangedEvent(new StackChangedEvent());
    request.addEvents(stackEvent);
    const inputEvent = new Event();
    inputEvent.setWebUiInputEvent(new WebUIInputEvent());
    request.addEvents(inputEvent);

    const stream = this.store.subscribeEvent(request);
    this.viewStackStream = stream;

    stream.on("error", () => {
      this.update({ connected: false });
      setTimeout(() => this.subscribeToViewAndStackChanges(), 1000);
    });

    stream.on("data", (response: SubscribeEventResponse) => {
      const evt = response.getEvent();
      if (!evt) return;

      const viewChangedEvent = evt.getViewChangedEvent();
      if (viewChangedEvent) {
        const newStatusBar = viewChangedEvent.getStatusBar()?.toObject();
        this.update({
          currentView: viewChangedEvent.getView()?.toObject() ?? null,
          ...(newStatusBar ? { statusBar: newStatusBar } : {}),
          connected: true,
        });
        return;
      }

      const stackChangedEvent = evt.getStackChangedEvent();
      if (stackChangedEvent) {
        this.update({
          stack: stackChangedEvent.toObject().stackList,
        });
        return;
      }

      const webUiInputEvent = evt.getWebUiInputEvent();
      if (webUiInputEvent) {
        synthesizeNavigationKey(webUiInputEvent.getCommand());
      }
    });
  }

  private subscribeToSystemMetrics(): void {
    if (this.metricsStream) {
      this.metricsStream.cancel();
    }

    const request = new SubscribeStoreRequest();
    request.setSelectorsList([
      "state.system.cpu_percent",
      "state.system.ram_percent",
      "state.audio.playback_volume",
    ]);

    const stream = this.store.subscribeStore(request);
    this.metricsStream = stream;

    stream.on("error", () => {
      setTimeout(() => this.subscribeToSystemMetrics(), 1000);
    });

    stream.on("data", (response: SubscribeStoreResponse) => {
      const results = response.getResultsList();
      if (results.length < 3) return;

      const cpuAny = results[0];
      const ramAny = results[1];
      const volumeAny = results[2];

      let cpuPercent = this.state.cpuPercent;
      let ramPercent = this.state.ramPercent;
      let volume = this.state.volume;

      if (cpuAny.getTypeUrl().includes("DoubleValue")) {
        cpuPercent = decodeDoubleValue(cpuAny.getValue_asU8());
      }

      if (ramAny.getTypeUrl().includes("DoubleValue")) {
        ramPercent = decodeDoubleValue(ramAny.getValue_asU8());
      }

      if (volumeAny.getTypeUrl().includes("DoubleValue")) {
        volume = decodeDoubleValue(volumeAny.getValue_asU8());
      }

      this.update({ cpuPercent, ramPercent, volume });
    });
  }
}

export const StateManagerContext = createContext<StateManager | null>(null);

export function useStateManager(): StateManager {
  const manager = useContext(StateManagerContext);
  if (!manager) {
    throw new Error("useStateManager must be used within StateManagerContext");
  }
  return manager;
}
