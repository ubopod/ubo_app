import { Box, Typography } from "@mui/material";

import { IDLE, STATUS } from "./colors";
import { DashboardCard } from "./DashboardCard";
import {
  DockerItemHealth,
  DockerItemStatus,
} from "../../bindings/ubo/v1/ubo_pb";
import type { DockerAppStatus, DockerServiceState } from "../../store/types";

interface Presentation {
  /** Nerd Font glyph. Filled dot = up, hollow dot = down, triangle = fault. */
  glyph: string;
  color: string;
  text: string;
}

// Health outranks lifecycle status, the same precedence `_update_app_badge`
// applies on the device (`ubo_app/services/080-docker/menus.py`). With
// `restart_policy: always` a crashing app is back to RUNNING seconds after it
// died, so the lifecycle status on its own would keep the row green while the
// app cycles.
const BY_HEALTH: Partial<Record<DockerItemHealth, Presentation>> = {
  [DockerItemHealth.DOCKER_ITEM_HEALTH_CRASH_LOOPING]: {
    glyph: "󰀦",
    color: STATUS.critical,
    text: "Crash looping",
  },
  [DockerItemHealth.DOCKER_ITEM_HEALTH_RECOVERED]: {
    glyph: "󰀦",
    color: STATUS.warning,
    text: "Restarted",
  },
};

const BY_STATUS: Partial<Record<DockerItemStatus, Presentation>> = {
  [DockerItemStatus.DOCKER_ITEM_STATUS_RUNNING]: {
    glyph: "󰪥",
    color: STATUS.good,
    text: "Running",
  },
  [DockerItemStatus.DOCKER_ITEM_STATUS_STARTING]: {
    glyph: "󰪥",
    color: STATUS.warning,
    text: "Starting",
  },
  [DockerItemStatus.DOCKER_ITEM_STATUS_FETCHING]: {
    glyph: "󰪥",
    color: STATUS.warning,
    text: "Fetching",
  },
  [DockerItemStatus.DOCKER_ITEM_STATUS_PROCESSING]: {
    glyph: "󰪥",
    color: STATUS.warning,
    text: "Working",
  },
  [DockerItemStatus.DOCKER_ITEM_STATUS_ERROR]: {
    glyph: "󰀦",
    color: STATUS.critical,
    text: "Errored",
  },
  // Image pulled, or container created — either way it is installed and off.
  [DockerItemStatus.DOCKER_ITEM_STATUS_AVAILABLE]: {
    glyph: "󰝦",
    color: IDLE,
    text: "Stopped",
  },
  [DockerItemStatus.DOCKER_ITEM_STATUS_CREATED]: {
    glyph: "󰝦",
    color: IDLE,
    text: "Stopped",
  },
};

const UNKNOWN: Presentation = { glyph: "󰋗", color: IDLE, text: "Unknown" };

function present(app: DockerAppStatus.AsObject): Presentation {
  return (
    BY_HEALTH[app.health ?? DockerItemHealth.DOCKER_ITEM_HEALTH_OK] ??
    BY_STATUS[app.status ?? DockerItemStatus.DOCKER_ITEM_STATUS_NOT_AVAILABLE] ??
    UNKNOWN
  );
}

/**
 * Every app whose image is on the device, one row each.
 *
 * Apps that have never been fetched never reach this component — the core
 * evicts an app from `DockerServiceState.apps` the moment it reports
 * `NOT_AVAILABLE`, so the map is exactly the set of installed apps.
 */
export function AppsCard({ docker }: { docker: DockerServiceState.AsObject }) {
  // A proto `map` carries no wire order, so without sorting the rows would
  // reshuffle every frame.
  const apps = [...(docker.apps?.itemsMap ?? [])]
    .map(([, app]) => app)
    .sort((a, b) => (a.label || a.id).localeCompare(b.label || b.id));

  return (
    <DashboardCard title="Apps" icon="󰆧">
      <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
        {apps.map((app) => {
          const { glyph, color, text } = present(app);
          return (
            <Box
              key={app.id}
              sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0 }}
            >
              {/* Colour is never the only channel — the status word beside it
                  says the same thing, per the convention in `colors.ts`. */}
              <Typography
                component="span"
                aria-hidden
                sx={{
                  fontFamily: "ArimoNerdFont",
                  color,
                  fontSize: 14,
                  lineHeight: 1,
                }}
              >
                {glyph}
              </Typography>
              <Typography
                variant="body2"
                sx={{
                  flex: 1,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {app.label || app.id}
              </Typography>
              <Typography variant="body2" fontWeight={600} sx={{ color }}>
                {text}
              </Typography>
            </Box>
          );
        })}
      </Box>
    </DashboardCard>
  );
}
