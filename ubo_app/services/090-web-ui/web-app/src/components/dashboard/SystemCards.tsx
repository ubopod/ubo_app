import { Box, Typography } from "@mui/material";

import { loadSeverity, NEUTRAL_ACCENT, STATUS } from "./colors";
import { DashboardCard, Stat } from "./DashboardCard";
import { formatBytes, formatRate, formatUptime } from "./format";
import { Gauge } from "./Gauge";
import type { SystemState } from "../../store/types";

interface SystemCardProps {
  system: SystemState.AsObject;
}

export function ProcessorCard({ system }: SystemCardProps) {
  const percent = system.cpuPercent ?? 0;
  const temperature = system.cpuTemperatureCelsius;

  return (
    <DashboardCard title="Processor" icon="󰻠">
      <Box sx={{ display: "flex", justifyContent: "center" }}>
        <Gauge
          fraction={percent / 100}
          value={`${Math.round(percent)}`}
          unit="%"
          label="CPU load"
          color={loadSeverity(percent)}
        />
      </Box>
      {temperature != null && (
        <Box sx={{ mt: 1.5 }}>
          <Stat
            icon="󰔏"
            label="Temperature"
            value={temperature.toFixed(1)}
            unit="°C"
          />
        </Box>
      )}
    </DashboardCard>
  );
}

export function MemoryCard({ system }: SystemCardProps) {
  const percent = system.ramPercent ?? 0;
  return (
    <DashboardCard title="Memory" icon="󰍛">
      <Box sx={{ display: "flex", justifyContent: "center" }}>
        <Gauge
          fraction={percent / 100}
          value={`${Math.round(percent)}`}
          unit="%"
          label="RAM used"
          color={loadSeverity(percent)}
        />
      </Box>
    </DashboardCard>
  );
}

export function StorageCard({ system }: SystemCardProps) {
  const percent = system.diskPercent ?? 0;
  const total = system.diskTotalBytes ?? 0;
  const used = system.diskUsedBytes ?? 0;

  return (
    <DashboardCard title="Storage" icon="󰋊">
      <Box sx={{ display: "flex", justifyContent: "center" }}>
        <Gauge
          fraction={percent / 100}
          value={`${Math.round(percent)}`}
          unit="%"
          label="Disk used"
          color={loadSeverity(percent)}
        />
      </Box>
      {total > 0 && (
        <Box sx={{ mt: 1.5 }}>
          <Stat
            label="Used"
            value={`${formatBytes(used)} / ${formatBytes(total)}`}
          />
        </Box>
      )}
    </DashboardCard>
  );
}

export function NetworkCard({ system }: SystemCardProps) {
  return (
    <DashboardCard title="Network" icon="󰛳">
      <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
        <Box sx={{ display: "flex", alignItems: "baseline", gap: 1 }}>
          <Typography
            component="span"
            sx={{ fontFamily: "ArimoNerdFont", color: STATUS.good, fontSize: 18 }}
          >
            󰁝
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
            Upload
          </Typography>
          <Typography variant="body2" fontWeight={600}>
            {formatRate(system.networkUploadBps ?? 0)}
          </Typography>
        </Box>
        <Box sx={{ display: "flex", alignItems: "baseline", gap: 1 }}>
          <Typography
            component="span"
            sx={{ fontFamily: "ArimoNerdFont", color: NEUTRAL_ACCENT, fontSize: 18 }}
          >
            󰁅
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
            Download
          </Typography>
          <Typography variant="body2" fontWeight={600}>
            {formatRate(system.networkDownloadBps ?? 0)}
          </Typography>
        </Box>
      </Box>
    </DashboardCard>
  );
}

export function UptimeCard({ system }: SystemCardProps) {
  return (
    <DashboardCard title="Uptime" icon="󰅐">
      <Typography variant="h5" fontWeight={600}>
        {formatUptime(system.bootTime ?? 0)}
      </Typography>
      <Box sx={{ mt: 1.5 }}>
        <Stat
          label="Load average"
          value={[
            system.loadAverage1 ?? 0,
            system.loadAverage5 ?? 0,
            system.loadAverage15 ?? 0,
          ]
            .map((value) => value.toFixed(2))
            .join("  ")}
        />
      </Box>
    </DashboardCard>
  );
}
