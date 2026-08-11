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
  // The service sub-slice, not `state.docker`: python-redux synthesizes a
  // per-image attribute on `DockerState` that has no proto counterpart, so
  // packing the parent raises and takes down the stream for *every* selector
  // above, not just this one. The service slice is a plain Immutable, and it
  // carries the per-app status projection the Apps tile renders.
  "state.docker.service",
] as const;

/**
 * Structural equality for the plain values `unpackAny` produces.
 *
 * `deserializeBinary(...).toObject()` builds a fresh object every message, so
 * every slice arrives with a new identity even when nothing about it changed —
 * and one `SubscribeStore` message carries *all* the selectors, so a CPU
 * reading ticking over would hand the clock, date and weather tiles new props
 * too. Reusing the previous reference when the value is unchanged is what makes
 * `React.memo` on the tiles mean anything.
 */
function isEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (typeof a !== "object") return false;

  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) {
      return false;
    }
    return a.every((item, index) => isEqual(item, b[index]));
  }

  const aRecord = a as Record<string, unknown>;
  const bRecord = b as Record<string, unknown>;
  const aKeys = Object.keys(aRecord);
  if (aKeys.length !== Object.keys(bRecord).length) return false;
  return aKeys.every(
    (key) =>
      Object.prototype.hasOwnProperty.call(bRecord, key) &&
      isEqual(aRecord[key], bRecord[key]),
  );
}

/** The freshly decoded value, or `previous` when the two are equivalent. */
function keepIdentity<T>(previous: T, next: T): T {
  return isEqual(previous, next) ? previous : next;
}

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
    docker: null,
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
    // A `SubscribeStore` message carries every selector, so most arrivals
    // change only one of them — and some change none at all. Re-rendering on
    // those costs a full pass over the dashboard for no visible difference.
    const changed = (Object.keys(partial) as (keyof AppState)[]).some(
      (key) => partial[key] !== this.state[key],
    );
    if (!changed) return;

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
        const [system, localization, sensors, volume, docker] = decoded;

        this.update({
          system: keepIdentity(
            this.state.system,
            (system as AppState["system"]) ?? this.state.system,
          ),
          localization: keepIdentity(
            this.state.localization,
            (localization as AppState["localization"]) ??
              this.state.localization,
          ),
          sensors: keepIdentity(
            this.state.sensors,
            (sensors as AppState["sensors"]) ?? this.state.sensors,
          ),
          // A device with the docker service disabled makes this selector
          // raise server-side, which arrives as Empty → null; the fallback
          // keeps `null` and the Apps tile simply never appears.
          docker: keepIdentity(
            this.state.docker,
            (docker as AppState["docker"]) ?? this.state.docker,
          ),
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
