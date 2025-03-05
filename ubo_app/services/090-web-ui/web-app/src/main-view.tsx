import { Status } from "./components/Status";
import { Display } from "./display";
import { StoreServiceClient } from "./generated/store/v1/StoreServiceClientPb";
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

export function MainView({
  status,
  store,
}: {
  status: StatusType | undefined;
  store: StoreServiceClient | null;
}) {
  if (!status) {
    return (
      <Status
        severity="info"
        message="Waiting for the server to report its status"
      />
    );
  }

  if (!store) {
    return (
      <Status
        severity="info"
        message="Waiting for the store to be initialized"
      />
    );
  }
  if (status.status === "ok") {
    if (status.docker === "running") {
      if (status.envoy === "running") {
        return <Display store={store} />;
      } else if (status.envoy === "not downloaded") {
        return (
          <Status
            message="Envoy image is not downloaded."
            action={{
              callback: () => request("download envoy"),
              label: "Download Envoy",
            }}
          />
        );
      } else if (status.envoy === "not running") {
        return (
          <Status
            message="Envoy container is not running."
            action={{
              callback: () => request("run envoy"),
              label: "Run Envoy",
            }}
          />
        );
      } else if (status.envoy === "failed") {
        return (
          <Status
            message="Failed to get envoy status."
            severity="error"
            action={{
              callback: () => request("remove envoy"),
              label: "Stop and remove container",
            }}
          />
        );
      } else if (status.envoy === "unknown") {
        return (
          <Status
            message="Envoy status: Unknown"
            severity="error"
            action={{
              callback: () => request("remove envoy"),
              label: "Stop and remove container",
            }}
          />
        );
      }
    } else if (status.docker === "not ready") {
      return <Status message="Docker not ready yet, please wait..." />;
    } else if (status.docker === "not installed") {
      return (
        <Status
          message="Docker is not installed."
          action={{
            callback: () => request("install docker"),
            label: "Install Docker",
          }}
        />
      );
    } else if (status.docker === "not running") {
      return (
        <Status
          message="Docker service is not running."
          action={{
            callback: () => request("run docker"),
            label: "Run Docker Service",
          }}
        />
      );
    } else if (status.docker === "failed") {
      return (
        <Status
          message="Failed to get docker status."
          severity="error"
          action={{
            callback: () => request("stop docker"),
            label: "Stop Docker Service",
          }}
        />
      );
    } else if (status.docker === "unknown") {
      <Status
        message="Docker status: Unknown"
        severity="error"
        action={{
          callback: () => request("stop docker"),
          label: "Stop Docker Service",
        }}
      />;
    }
  } else {
    return <div>Server is not ready</div>;
  }
}
