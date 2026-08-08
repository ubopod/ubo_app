import { createContext, useContext } from "react";

import { resilientStream, type ResilientStream } from "./resilient-stream";
import type { AppState } from "./types";
import { unpackAny } from "./unpack-any";
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

// Selectors for the one and only `SubscribeStore` stream, in wire order —
// `SubscribeStoreResponse.results` is positional, so this array *is* the
// contract. Whole slices rather than individual scalars: one selector can
// carry a whole dashboard's worth of fields, and the browser's six-connection
// HTTP/1.1 limit (see the note in `action-dispatcher.ts`) leaves no room for a
// second stream.
const STORE_SELECTORS = [
  "state.system",
  "state.localization",
  "state.sensors",
  "state.audio.playback_volume",
] as const;

export type StateListener = (state: AppState) => void;

export class StateManager {
  private state: AppState = {
    currentView: null,
    statusBar: null,
    stack: [],
    connected: false,
    system: null,
    localization: null,
    sensors: null,
    volume: 0,
  };

  private listeners: Set<StateListener> = new Set();
  private streams: ResilientStream[] = [];

  constructor(private store: StoreServiceClient) {
    this.streams = [
      this.subscribeToViewAndStackChanges(),
      this.subscribeToSystemMetrics(),
    ];
  }

  /**
   * Cancel every subscription. Call from the owner's unmount cleanup —
   * otherwise the streams stay open and keep reconnecting forever, and the
   * browser's 6-connections-per-origin cap is reached after a restart or two
   * (see the note in `action-dispatcher.ts`).
   */
  dispose(): void {
    for (const stream of this.streams) {
      stream.dispose();
    }
    this.streams = [];
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

  private subscribeToViewAndStackChanges(): ResilientStream {
    const buildRequest = () => {
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
      return request;
    };

    // The server replays the current view and stack to every new subscriber,
    // so a reconnect restores the UI without anyone touching the device.
    return resilientStream(
      () => this.store.subscribeEvent(buildRequest()),
      (response: SubscribeEventResponse) => {
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
      },
      () => this.update({ connected: false }),
    );
  }

  private subscribeToSystemMetrics(): ResilientStream {
    const buildRequest = () => {
      const request = new SubscribeStoreRequest();
      request.setSelectorsList([...STORE_SELECTORS]);
      return request;
    };

    return resilientStream(
      () => this.store.subscribeStore(buildRequest()),
      (response: SubscribeStoreResponse) => {
        const results = response.getResultsList();
        if (results.length !== STORE_SELECTORS.length) return;

        // A selector that raised server-side comes back as Empty → null; keep
        // the previous value rather than blanking a tile on one bad frame.
        const decoded = results.map((result) =>
          unpackAny(result.getTypeUrl(), result.getValue_asU8()),
        );
        const [system, localization, sensors, volume] = decoded;

        this.update({
          system: (system as AppState["system"]) ?? this.state.system,
          localization:
            (localization as AppState["localization"]) ??
            this.state.localization,
          sensors: (sensors as AppState["sensors"]) ?? this.state.sensors,
          volume: typeof volume === "number" ? volume : this.state.volume,
        });
      },
    );
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
