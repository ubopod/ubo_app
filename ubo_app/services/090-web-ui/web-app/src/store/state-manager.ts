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
} from "../bindings/ubo/v1/ubo_pb";

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
  private viewStream: ReturnType<StoreServiceClient["subscribeEvent"]> | null =
    null;
  private stackStream: ReturnType<
    StoreServiceClient["subscribeEvent"]
  > | null = null;
  private metricsStream: ReturnType<
    StoreServiceClient["subscribeStore"]
  > | null = null;

  constructor(private store: StoreServiceClient) {
    this.subscribeToViewChanges();
    this.subscribeToStackChanges();
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

  private subscribeToViewChanges(): void {
    if (this.viewStream) {
      this.viewStream.cancel();
    }

    const event = new Event();
    event.setViewChangedEvent(new ViewChangedEvent());

    const request = new SubscribeEventRequest();
    request.setEvent(event);

    const stream = this.store.subscribeEvent(request);
    this.viewStream = stream;

    stream.on("error", () => {
      this.update({ connected: false });
      setTimeout(() => this.subscribeToViewChanges(), 1000);
    });

    stream.on("data", (response: SubscribeEventResponse) => {
      const viewEvent = response.getEvent()?.getViewChangedEvent();
      if (!viewEvent) return;

      const newStatusBar = viewEvent.getStatusBar()?.toObject();
      this.update({
        currentView: viewEvent.getView()?.toObject() ?? null,
        ...(newStatusBar ? { statusBar: newStatusBar } : {}),
        connected: true,
      });
    });
  }

  private subscribeToStackChanges(): void {
    if (this.stackStream) {
      this.stackStream.cancel();
    }

    const event = new Event();
    event.setStackChangedEvent(new StackChangedEvent());

    const request = new SubscribeEventRequest();
    request.setEvent(event);

    const stream = this.store.subscribeEvent(request);
    this.stackStream = stream;

    stream.on("error", () => {
      setTimeout(() => this.subscribeToStackChanges(), 1000);
    });

    stream.on("data", (response: SubscribeEventResponse) => {
      const stackEvent = response.getEvent()?.getStackChangedEvent();
      if (!stackEvent) return;

      this.update({
        stack: stackEvent.toObject().stackList,
      });
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
