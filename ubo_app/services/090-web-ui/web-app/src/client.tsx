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

import { ThemeSwitch } from "./components/ThemeSwitch";
import { StoreServiceClient } from "./generated/store/v1/StoreServiceClientPb";
import { Inputs } from "./inputs";
import { MainView } from "./main-view";
import { InputDescription, StatusType } from "./types";

export function Root({ inputs }: { inputs: InputDescription[] }) {
  const [status, setStatus] = useState<StatusType | undefined>();
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
          inputs={status == null ? inputs : status.inputs}
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

export function init(inputs: InputDescription[]) {
  const rootElement = document.getElementById("web-app-root");
  if (rootElement) {
    const root = createRoot(rootElement);
    root.render(
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Root inputs={inputs} />
      </ThemeProvider>,
    );
  }
}
