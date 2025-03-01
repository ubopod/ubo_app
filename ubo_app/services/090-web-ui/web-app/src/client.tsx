import {
  createTheme,
  CssBaseline,
  ThemeProvider,
  AppBar,
  Container,
} from "@mui/material";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/roboto/300.css";
import "@fontsource/roboto/400.css";
import "@fontsource/roboto/500.css";
import "@fontsource/roboto/700.css";

import { ThemeSwitch } from "./components/ThemeSwitch";
import { Display } from "./display";
import { StoreServiceClient } from "./generated/store/v1/StoreServiceClientPb";
import { Inputs } from "./inputs";
import { Action, StatusType } from "./types";

function request(action: Action) {
  fetch("/action/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action }),
  });
}

export function Root() {
  const [status, setStatus] = useState<StatusType | undefined>();
  const [store, setStore] = useState<StoreServiceClient | null>(null);

  useEffect(() => {
    const store = new StoreServiceClient(
      `${window.location.protocol}//${window.location.hostname}:${window.GRPC_ENVOY_LISTEN_PORT}`,
      null,
      null,
    );
    setStore(store);

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

  if (!status) {
    return "Waiting for the server to report its status";
  }

  if (!store) {
    return "Waiting for the store to be initialized";
  }

  if (status.status === "ok") {
    if (status.docker === "running") {
      if (status.envoy === "running") {
        return (
          <>
            <AppBar position="static" variant="outlined" color="inherit">
              <Container maxWidth="xs">
                <ThemeSwitch />
              </Container>
            </AppBar>
            <Display store={store} />
            <Inputs inputs={status.inputs} store={store} />
          </>
        );
      } else if (status.envoy === "not downloaded") {
        return (
          <div>
            Envoy is not downloaded{" "}
            <button onClick={() => request("download envoy")}>
              Download Envoy
            </button>
          </div>
        );
      } else if (status.envoy === "not running") {
        return (
          <div>
            Envoy is not running{" "}
            <button onClick={() => request("run envoy")}>Run Envoy</button>
          </div>
        );
      } else if (status.envoy === "unknown") {
        return <div>Envoy status is unknown</div>;
      }
    } else if (status.docker === "not ready") {
      return <div>Docker is not ready</div>;
    } else if (status.docker === "not installed") {
      return <div>Docker is not installed</div>;
    } else if (status.docker === "not running") {
      return <div>Docker is not running</div>;
    } else if (status.docker === "unknown") {
      return <div>Docker status is unknown</div>;
    }
  } else {
    return <div>Server is not ready</div>;
  }
}

const theme = createTheme({
  colorSchemes: {
    dark: true,
  },
});

export function init() {
  const rootElement = document.getElementById("web-app-root");
  if (rootElement) {
    const root = createRoot(rootElement);
    root.render(
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Root />
      </ThemeProvider>,
    );
  }
}
