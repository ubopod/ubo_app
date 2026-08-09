import { Box, Typography } from "@mui/material";
import { memo, useMemo, type ReactNode } from "react";

import { sensorCards } from "./SensorCards";
import {
  MemoryCard,
  NetworkCard,
  ProcessorCard,
  StorageCard,
  UptimeCard,
} from "./SystemCards";
import { ClockCard, DateCard } from "./TimeCards";
import { WeatherCard } from "./WeatherCard";
import type { StoreServiceClient } from "../../bindings/store/v1/StoreServiceClientPb";
import type { AppState } from "../../store/types";
import { useAppState } from "../../store/useAppState";
import { MainMenuTile } from "../MainMenuTile";

// Memoised once, here, rather than at each definition: every card takes a
// single state slice, and `StateManager` now keeps a slice's identity stable
// across messages that did not change it. That makes the default shallow
// compare exact — a CPU reading ticking over re-renders the processor and
// memory cards and leaves the clock, date and weather tiles untouched.
const Weather = memo(WeatherCard);
const Date_ = memo(DateCard);
const Clock = memo(ClockCard);
const Processor = memo(ProcessorCard);
const Memory = memo(MemoryCard);
const Storage = memo(StorageCard);
const Network = memo(NetworkCard);
const Uptime = memo(UptimeCard);

/**
 * One dashboard widget.
 *
 * Declared as data rather than inlined JSX so that making the set
 * user-selectable later is a matter of filtering on `id` — no restructuring.
 */
interface DashboardTileSpec {
  id: string;
  /** Columns to span at the widest breakpoint. */
  span: number;
  isAvailable: (state: AppState) => boolean;
  render: (state: AppState) => ReactNode;
}

const TILES: DashboardTileSpec[] = [
  {
    id: "weather",
    span: 1,
    // The card explains "location not detected yet" itself, so it stays
    // visible as soon as the localization slice exists at all.
    isAvailable: (state) => state.localization !== null,
    render: (state) => <Weather localization={state.localization!} />,
  },
  {
    id: "date",
    span: 1,
    isAvailable: (state) => Boolean(state.localization?.date),
    render: (state) => <Date_ localization={state.localization!} />,
  },
  {
    id: "clock",
    span: 1,
    isAvailable: (state) => Boolean(state.localization?.clock),
    render: (state) => <Clock localization={state.localization!} />,
  },
  {
    id: "cpu",
    span: 1,
    isAvailable: (state) => state.system !== null,
    render: (state) => <Processor system={state.system!} />,
  },
  {
    id: "ram",
    span: 1,
    isAvailable: (state) => state.system !== null,
    render: (state) => <Memory system={state.system!} />,
  },
  {
    id: "disk",
    span: 1,
    // Disk arrives on a slower loop than the rest of the slice; until the
    // first sample lands, a 0 % meter would be a lie.
    isAvailable: (state) => (state.system?.diskTotalBytes ?? 0) > 0,
    render: (state) => <Storage system={state.system!} />,
  },
  {
    id: "network",
    span: 1,
    isAvailable: (state) => state.system !== null,
    render: (state) => <Network system={state.system!} />,
  },
  {
    id: "uptime",
    span: 1,
    isAvailable: (state) => (state.system?.bootTime ?? 0) > 0,
    render: (state) => <Uptime system={state.system!} />,
  },
];

export function Dashboard({ store }: { store: StoreServiceClient }) {
  const state = useAppState();

  const tiles = TILES.filter((tile) => tile.isAvailable(state)).map((tile) => ({
    id: tile.id,
    span: tile.span,
    node: tile.render(state),
  }));

  // The sensor cards are built from the slice rather than by a component, so
  // memoising the slice buys nothing unless the build is memoised too.
  const sensors = useMemo(
    () =>
      state.sensors
        ? sensorCards(state.sensors).map((card) => ({ ...card, span: 1 }))
        : [],
    [state.sensors],
  );

  const isWaiting = tiles.length === 0 && sensors.length === 0;

  return (
    <Box data-dashboard sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {/* The one way out of the dashboard, pinned above the widgets: it is an
          action, not a readout, and must never scroll out of reach. */}
      <MainMenuTile store={store} />

      {isWaiting ? (
        <Typography variant="body2" color="text.secondary">
          Waiting for the first readings…
        </Typography>
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              sm: "repeat(2, minmax(0, 1fr))",
              md: "repeat(3, minmax(0, 1fr))",
              lg: "repeat(4, minmax(0, 1fr))",
            },
            gap: 2,
            alignItems: "stretch",
          }}
        >
          {[...tiles, ...sensors].map((tile) => (
            <Box
              key={tile.id}
              sx={{
                gridColumn: {
                  xs: "span 1",
                  sm: `span ${Math.min(tile.span, 2)}`,
                  md: `span ${Math.min(tile.span, 3)}`,
                  lg: `span ${tile.span}`,
                },
              }}
            >
              {tile.node}
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}
