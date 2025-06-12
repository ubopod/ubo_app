import {
  createTheme,
  CssBaseline,
  ThemeProvider,
  AppBar,
  Container,
  Stack,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/roboto/300.css";
import "@fontsource/roboto/400.css";
import "@fontsource/roboto/500.css";
import "@fontsource/roboto/700.css";

import { StoreServiceClient } from "./bindings/store/v1/StoreServiceClientPb";
import { WebUIState } from "./bindings/ubo/v1/ubo_pb";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { Inputs } from "./inputs";
import { MainView } from "./main-view";
import { StatusType } from "./types";

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
        `${window.location.protocol}//${window.location.hostname}:${window.GRPC_ENVOY_LISTEN_PORT}`,
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
      } catch {
        setStatus(undefined);
      }
    }
    checkStatus();
    const interval = setInterval(checkStatus, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <>
      <AppBar position="static" variant="outlined" color="inherit">
        <Container maxWidth="xs">
          <ThemeSwitch />
        </Container>
      </AppBar>
      <Container maxWidth="xs" component={Stack} spacing={2} py={2}>
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
      </Container>
    </>
  );
}

const theme = createTheme({
  colorSchemes: {
    dark: true,
  },
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
