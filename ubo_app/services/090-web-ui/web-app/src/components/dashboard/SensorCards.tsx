import { Box, Typography } from "@mui/material";

import { NEUTRAL_ACCENT, STATUS } from "./colors";
import { DashboardCard, Stat } from "./DashboardCard";
import { formatReading } from "./format";
import { Gauge } from "./Gauge";
import { displaySpec, rangeFraction } from "./sensor-display";
import { SensorStatus } from "../../bindings/ubo/v1/ubo_pb";
import type { SensorDeviceState, SensorsState } from "../../store/types";

interface SensorCardProps {
  device: SensorDeviceState.AsObject;
}

function SensorCard({ device }: SensorCardProps) {
  const entities = device.entities?.itemsList ?? [];

  if (device.status !== SensorStatus.SENSOR_STATUS_ACTIVE) {
    return (
      <DashboardCard title={device.label} icon="󰡵">
        <Typography variant="body2" sx={{ color: STATUS.critical }}>
          <span style={{ fontFamily: "ArimoNerdFont" }}>󰀦</span>{" "}
          {device.status === SensorStatus.SENSOR_STATUS_UNSUPPORTED
            ? "Driver unavailable"
            : device.status === SensorStatus.SENSOR_STATUS_AMBIGUOUS
              ? "Ambiguous address"
              : "Read error"}
        </Typography>
      </DashboardCard>
    );
  }

  // Readings with a meaningful range get a meter; the rest are plain stats,
  // laid out below so the card still reads as one group.
  const metered = entities.filter(
    (entity) => displaySpec(entity.key, entity.deviceClass).range !== undefined,
  );
  const plain = entities.filter(
    (entity) => displaySpec(entity.key, entity.deviceClass).range === undefined,
  );

  return (
    <DashboardCard title={device.label} icon="󰡵">
      {metered.length > 0 && (
        <Box
          sx={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            gap: 1.5,
          }}
        >
          {metered.map((entity) => {
            const spec = displaySpec(entity.key, entity.deviceClass);
            const hasValue = entity.value != null;
            return (
              <Gauge
                key={entity.key}
                size={88}
                // A failed read shows an empty meter and a dash, never a zero.
                fraction={
                  hasValue && spec.range
                    ? rangeFraction(entity.value as number, spec.range)
                    : 0
                }
                value={formatReading(entity.value, entity.precision)}
                unit={entity.unit || undefined}
                label={entity.name || entity.key}
                color={NEUTRAL_ACCENT}
              />
            );
          })}
        </Box>
      )}
      {plain.length > 0 && (
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            gap: 0.75,
            mt: metered.length > 0 ? 1.5 : 0,
          }}
        >
          {plain.map((entity) => (
            <Stat
              key={entity.key}
              icon={displaySpec(entity.key, entity.deviceClass).icon}
              label={entity.name || entity.key}
              value={formatReading(entity.value, entity.precision)}
              unit={entity.unit || undefined}
            />
          ))}
        </Box>
      )}
      {entities.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No readings yet
        </Typography>
      )}
    </DashboardCard>
  );
}

/** One card per detected sensor. Renders nothing when the bus is empty. */
export function sensorCards(sensors: SensorsState.AsObject): {
  id: string;
  node: React.ReactNode;
}[] {
  const devices = sensors.devices?.itemsMap ?? [];
  return devices.map(([id, device]) => ({
    id: `sensors:${id}`,
    node: <SensorCard key={id} device={device} />,
  }));
}
