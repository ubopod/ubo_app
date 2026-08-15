import {
  createTheme,
  CssBaseline,
  ThemeProvider,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/roboto/300.css";
import "@fontsource/roboto/400.css";
import "@fontsource/roboto/500.css";
import "@fontsource/roboto/700.css";
import "./global.css";

import { StoreServiceClient } from "./bindings/store/v1/StoreServiceClientPb";
import { WebUIState } from "./bindings/ubo/v1/ubo_pb";
import { Inputs } from "./inputs";
import { MainView } from "./main-view";
import { onPostDispatch } from "./store/action-dispatcher";
import { getGrpcWebBaseUrl } from "./store/grpc-endpoint";
import { StatusType } from "./types";

function triggerDownloads(
  downloads: { token: string; filename: string }[],
): void {
  for (const { token, filename } of downloads) {
    const a = document.createElement("a");
    a.href = `/download/${token}`;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }
}

export function Root({ state }: { state: string }) {
  const [status, setStatus] = useState<StatusType | undefined>();
  const inputDescriptions = WebUIState.deserializeBinary(
    new Uint8Array(
      ((status == null ? state : status.state).match(/.{1,2}/g) || []).map(
        (byte) => parseInt(byte, 16),
      ),
    ),
  ).toObject().activeInputsList;
  const store = useMemo<StoreServiceClient | null>(
    () =>
      new StoreServiceClient(
        getGrpcWebBaseUrl(),
        null,
        null,
      ),
    [],
  );

  useEffect(() => {
    async function checkStatus() {
      try {
        const response = await fetch("/status");
        const data: StatusType = await response.json();
        setStatus(data);
        // Trigger browser downloads for any pending files
        if (data.pending_downloads?.length) {
          triggerDownloads(data.pending_downloads);
        }
      } catch {
        setStatus(undefined);
      }
    }
    checkStatus();
    const interval = setInterval(checkStatus, 5000);
    // Refresh status immediately after any action dispatch
    const unsubscribe = onPostDispatch(() => checkStatus());
    return () => {
      clearInterval(interval);
      unsubscribe();
    };
  }, []);

  return (
    <>
      <MainView status={status} store={store} />
      <Inputs
        inputs={inputDescriptions}
        isGrpcConnected={
          status?.status === "ok" &&
          status?.docker === "running" &&
          status?.envoy === "running"
        }
        store={store}
      />
    </>
  );
}

const theme = createTheme({
  colorSchemes: {
    dark: true,
  },
  defaultColorScheme: "dark",
});

export function init(state: string) {
  const rootElement = document.getElementById("web-app-root");
  if (rootElement) {
    const root = createRoot(rootElement);
    root.render(
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Root state={state} />
      </ThemeProvider>,
    );
  }
}
