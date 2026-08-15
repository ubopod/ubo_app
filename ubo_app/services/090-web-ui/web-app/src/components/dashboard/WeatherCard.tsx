import { Box, Typography, useTheme } from "@mui/material";

import { DashboardCard } from "./DashboardCard";
import { WeatherIcon } from "./WeatherIcon";
import type { LocalizationState } from "../../store/types";

// Display phrases for the MET Norway symbol codes, keyed by the code with its
// day/night suffix stripped. Mirrors `SYMBOL_PHRASES` in
// `ubo_app/services/010-localization/weather.py`, worded for reading rather
// than for speech.
const PHRASES: Record<string, string> = {
  clearsky: "Clear",
  fair: "Fair",
  partlycloudy: "Partly cloudy",
  cloudy: "Cloudy",
  fog: "Fog",
  rain: "Rain",
  lightrain: "Light rain",
  heavyrain: "Heavy rain",
  rainshowers: "Showers",
  lightrainshowers: "Light showers",
  heavyrainshowers: "Heavy showers",
  drizzle: "Drizzle",
  sleet: "Sleet",
  lightsleet: "Light sleet",
  heavysleet: "Heavy sleet",
  sleetshowers: "Sleet showers",
  lightsleetshowers: "Light sleet showers",
  heavysleetshowers: "Heavy sleet showers",
  snow: "Snow",
  lightsnow: "Light snow",
  heavysnow: "Heavy snow",
  snowshowers: "Snow showers",
  lightsnowshowers: "Light snow showers",
  heavysnowshowers: "Heavy snow showers",
  rainandthunder: "Rain and thunder",
  rainshowersandthunder: "Showers and thunder",
  thunderstorm: "Thunderstorm",
  heavyrainandthunder: "Heavy rain and thunder",
  snowandthunder: "Snow and thunder",
  sleetandthunder: "Sleet and thunder",
};

function describe(symbolCode: string): string {
  let base = symbolCode;
  for (const suffix of ["_day", "_night", "_polartwilight"]) {
    if (base.endsWith(suffix)) {
      base = base.slice(0, -suffix.length);
      break;
    }
  }
  // Unknown codes still read as something, rather than a raw token.
  return (
    PHRASES[base] ??
    base.replace(/[_-]/g, " ").replace(/^./, (c) => c.toUpperCase())
  );
}

interface WeatherCardProps {
  localization: LocalizationState.AsObject;
}

export function WeatherCard({ localization }: WeatherCardProps) {
  const theme = useTheme();
  const weather = localization.weather;
  const location = localization.location;

  const place = [location?.city, location?.country]
    .filter(Boolean)
    .join(", ");

  if (!weather) {
    return (
      <DashboardCard title="Weather" icon="󰖐">
        <Typography variant="body2" color="text.secondary">
          {location ? "Fetching forecast…" : "Location not detected yet"}
        </Typography>
      </DashboardCard>
    );
  }

  return (
    <DashboardCard title="Weather" icon="󰖐">
      {/* Single-column tile: the icon and temperature share one centred row,
          with everything else stacked under it, so nothing has to compete for
          horizontal space at the narrowest breakpoint. */}
      <Box sx={{ textAlign: "center" }}>
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 1,
          }}
        >
          <WeatherIcon
            symbolCode={weather.symbolCode}
            size={64}
            cloudColor={theme.palette.text.secondary}
          />
          <Typography variant="h4" fontWeight={600} lineHeight={1.1}>
            {Math.round(weather.temperatureDisplayValue ?? weather.temperatureCelsius)}
            {weather.temperatureDisplayUnit ?? "°C"}
          </Typography>
        </Box>
        <Typography variant="body2" color="text.secondary">
          {describe(weather.symbolCode)}
        </Typography>
        {place && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{
              display: "block",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            <span style={{ fontFamily: "ArimoNerdFont" }}>󰍎</span> {place}
          </Typography>
        )}
        {weather.windSpeedDisplayValue != null && (
          <Typography variant="caption" color="text.secondary" display="block">
            <span style={{ fontFamily: "ArimoNerdFont" }}>󰖝</span>{" "}
            {weather.windSpeedDisplayValue.toFixed(1)} {weather.windSpeedDisplayUnit}
          </Typography>
        )}
      </Box>
    </DashboardCard>
  );
}
