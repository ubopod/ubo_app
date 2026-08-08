import { Box, Typography } from "@mui/material";

import { NEUTRAL_ACCENT } from "./colors";
import { DashboardCard } from "./DashboardCard";
import { SevenSegmentClock } from "./SevenSegment";
import type { LocalizationState } from "../../store/types";

interface TimeCardProps {
  localization: LocalizationState.AsObject;
}

/**
 * Split the device's "HH:MM" into display digits plus a period.
 *
 * The leading hour zero is blanked rather than dropped, the way a real clock
 * does it — dropping it would shift every other digit at 10 o'clock and again
 * at 1, and a clock whose digits jump around is distracting.
 */
function toDisplay(clock: string): { digits: string; period: string } | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(clock);
  if (!match) return null;

  const hours24 = Number(match[1]);
  if (hours24 > 23) return null;

  const period = hours24 >= 12 ? "PM" : "AM";
  const hours12 = hours24 % 12 || 12;
  const padded = String(hours12).padStart(2, "0");

  return {
    digits: `${padded[0] === "0" ? " " : padded[0]}${padded[1]}${match[2]}`,
    period,
  };
}

export function ClockCard({ localization }: TimeCardProps) {
  const display = toDisplay(localization.clock ?? "");

  return (
    <DashboardCard title="Time" icon="󰅐">
      {display ? (
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 1.5,
            justifyContent: "center",
          }}
        >
          <Box sx={{ flex: 1, minWidth: 0, maxWidth: 260 }}>
            <SevenSegmentClock digits={display.digits} color={NEUTRAL_ACCENT} />
          </Box>
          <Typography
            variant="h6"
            fontWeight={700}
            sx={{ color: NEUTRAL_ACCENT, letterSpacing: 1 }}
          >
            {display.period}
          </Typography>
        </Box>
      ) : (
        <Typography variant="body2" color="text.secondary">
          Waiting for the clock…
        </Typography>
      )}
    </DashboardCard>
  );
}

/**
 * Format the device's "YYYY-MM-DD".
 *
 * Built from the parts rather than parsed: `new Date('2026-08-08')` is read as
 * UTC midnight, which renders as the previous day for any viewer west of
 * Greenwich. The explicit constructor makes it local midnight.
 */
function toParts(date: string): { weekday: string; monthDay: string } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return null;

  const parsed = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  );
  if (Number.isNaN(parsed.getTime())) return null;

  return {
    weekday: parsed.toLocaleDateString(undefined, { weekday: "long" }),
    monthDay: parsed.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    }),
  };
}

export function DateCard({ localization }: TimeCardProps) {
  const parts = toParts(localization.date ?? "");

  return (
    <DashboardCard title="Date" icon="󰃭">
      {parts ? (
        <Box sx={{ textAlign: "center" }}>
          <Typography variant="h5" fontWeight={500} color="text.secondary">
            {parts.weekday}
          </Typography>
          <Typography variant="h3" fontWeight={700} lineHeight={1.1}>
            {parts.monthDay}
          </Typography>
        </Box>
      ) : (
        <Typography variant="body2" color="text.secondary">
          Waiting for the date…
        </Typography>
      )}
    </DashboardCard>
  );
}
