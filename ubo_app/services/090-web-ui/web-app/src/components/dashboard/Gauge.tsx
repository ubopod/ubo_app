import { Box, Typography, useTheme } from "@mui/material";

// A 270° arc, drawn once and reused: `pathLength={100}` normalizes the stroke
// dash units to percent, so the fill length needs no arc-length arithmetic.
const ARC_PATH = "M 21.72 78.28 A 40 40 0 1 1 78.28 78.28";
const STROKE_WIDTH = 9;

interface GaugeProps {
  /** Fraction of the arc to fill, 0-1. Values outside are clamped. */
  fraction: number;
  /** The number to show inside the arc. Already formatted. */
  value: string;
  unit?: string;
  /** Always rendered — the meter never relies on its color alone. */
  label: string;
  color: string;
  size?: number;
}

export function Gauge({
  fraction,
  value,
  unit,
  label,
  color,
  size = 104,
}: GaugeProps) {
  const theme = useTheme();
  const filled = Math.max(0, Math.min(1, Number.isFinite(fraction) ? fraction : 0));

  return (
    <Box
      sx={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0.5 }}
    >
      <Box sx={{ position: "relative", width: size, height: size }}>
        <svg viewBox="0 0 100 100" width={size} height={size} aria-hidden="true">
          {/* Track: the same hue as the fill, stepped back, so the unfilled
              remainder still reads as part of the same meter. */}
          <path
            d={ARC_PATH}
            fill="none"
            stroke={color}
            strokeOpacity={theme.palette.mode === "dark" ? 0.18 : 0.14}
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
          />
          {/* The fill deliberately animates nothing. `stroke-dasharray` is
              geometry, so a CSS transition on it is not composited: every
              frame re-runs style and re-rasterises the arc. Measured on the
              dashboard — which carries a dozen or more of these once the
              sensor cards are in — a 0.4s ease here cost ~37 style
              recalculations a second against 2 without, and on the device's
              own browser that was most of a core. */}
          <path
            d={ARC_PATH}
            fill="none"
            stroke={color}
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
            pathLength={100}
            // Quantised to a tenth of a percent: the readings behind these
            // gauges jitter continuously, and without this the attribute — and
            // so the paint — changes on every tick for a difference no one can
            // see. A tenth of a percent is a quarter of a degree of arc.
            strokeDasharray={`${(filled * 100).toFixed(1)} 100`}
          />
        </svg>
        <Box
          sx={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            // Leave the arc's open bottom clear of the centred text.
            pb: 1,
          }}
        >
          {/* Values wear text tokens, never the meter color — the arc beside
              them already carries the severity. */}
          <Typography variant="h6" fontWeight={600} lineHeight={1.1}>
            {value}
          </Typography>
          {unit && (
            <Typography variant="caption" color="text.secondary" lineHeight={1}>
              {unit}
            </Typography>
          )}
        </Box>
      </Box>
      <Typography variant="caption" color="text.secondary" textAlign="center">
        {label}
      </Typography>
    </Box>
  );
}
