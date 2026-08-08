import { Box, Paper, Typography } from "@mui/material";
import type { ReactNode } from "react";

interface DashboardCardProps {
  title: string;
  /** Nerd Font glyph shown beside the title. */
  icon?: string;
  children: ReactNode;
  /** Column span in the dashboard grid. */
  span?: number;
}

export function DashboardCard({ title, icon, children }: DashboardCardProps) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2,
        border: 1,
        borderColor: "divider",
        backgroundColor: "background.paper",
        display: "flex",
        flexDirection: "column",
        gap: 1.5,
        height: "100%",
      }}
    >
      <Typography
        variant="overline"
        color="text.secondary"
        sx={{ display: "flex", alignItems: "center", gap: 0.75, lineHeight: 1.6 }}
      >
        {icon && <span style={{ fontFamily: "ArimoNerdFont" }}>{icon}</span>}
        {title}
      </Typography>
      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        {children}
      </Box>
    </Paper>
  );
}

interface StatProps {
  label: string;
  value: string;
  unit?: string;
  icon?: string;
}

/** A labelled number, for readings with no meaningful range to meter against. */
export function Stat({ label, value, unit, icon }: StatProps) {
  return (
    <Box sx={{ display: "flex", alignItems: "baseline", gap: 1, minWidth: 0 }}>
      {icon && (
        <Typography
          component="span"
          sx={{ fontFamily: "ArimoNerdFont", color: "text.secondary", fontSize: 16 }}
        >
          {icon}
        </Typography>
      )}
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
      >
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={600}>
        {value}
        {unit && (
          <Typography component="span" variant="caption" color="text.secondary">
            {" "}
            {unit}
          </Typography>
        )}
      </Typography>
    </Box>
  );
}
