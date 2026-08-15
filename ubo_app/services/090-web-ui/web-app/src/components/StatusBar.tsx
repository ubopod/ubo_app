import {
  FiberManualRecord,
  Mic,
  PowerSettingsNew,
  RestartAlt,
  Stop,
} from "@mui/icons-material";
import {
  Box,
  IconButton,
  LinearProgress,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Typography,
} from "@mui/material";
import { useCallback, useState } from "react";

import { NotificationBell } from "./NotificationBell";
import { VolumeControl } from "./VolumeControl";
import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { StatusBarData } from "../bindings/ubo/v1/ubo_pb";
import { powerOff, reboot } from "../store/action-dispatcher";
import {
  isBrowserMicActive,
  startBrowserMic,
  stopBrowserMic,
} from "../store/audio-input";
import { useAppState } from "../store/useAppState";
import { parseColoredIcon } from "../utils/color-markup";

interface StatusBarProps {
  data: StatusBarData.AsObject | null;
  store: StoreServiceClient;
}

export function StatusBar({ data, store }: StatusBarProps) {
  const { system } = useAppState();
  const icons = data?.icons?.itemsList ?? [];
  const progressNotifications =
    data?.progressNotifications?.itemsList ?? [];
  const clock = data?.clock ?? "";

  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const menuOpen = Boolean(anchorEl);
  const [micActive, setMicActive] = useState(isBrowserMicActive());

  const handleMicToggle = useCallback(() => {
    if (micActive) {
      stopBrowserMic(store);
      setMicActive(false);
    } else {
      startBrowserMic(store)
        .then(() => setMicActive(true))
        .catch((error: unknown) => {
          // Keep the icon idle and tell the user why (e.g. insecure context)
          // instead of failing silently with an uncaught rejection.
          window.alert(error instanceof Error ? error.message : String(error));
        });
    }
  }, [store, micActive]);

  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        px: 2,
        py: 0.5,
        backgroundColor: "background.paper",
        borderBottom: 1,
        borderColor: "divider",
        minHeight: 40,
        gap: 1,
      }}
    >
      {/* Status icons */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, flex: 1 }}>
        {icons.map((icon, index) => {
          const parsed = parseColoredIcon(icon.symbol ?? "");
          return (
            <Typography
              key={index}
              sx={{
                fontFamily: "ArimoNerdFont",
                fontSize: 18,
                color: parsed.color || icon.color || "text.secondary",
                lineHeight: 1,
              }}
            >
              {parsed.icon}
            </Typography>
          );
        })}
        {data?.isRecordingAudio && (
          <FiberManualRecord sx={{ fontSize: 14, color: "error.main" }} />
        )}
      </Box>

      {/* Progress indicators */}
      {progressNotifications.length > 0 && (
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, mx: 1 }}>
          {progressNotifications.map((pn) => (
            <LinearProgress
              key={pn.id}
              variant={
                pn.progress != null ? "determinate" : "indeterminate"
              }
              value={(pn.progress ?? 0) * 100}
              sx={{
                width: 40,
                height: 4,
                borderRadius: 2,
                "& .MuiLinearProgress-bar": {
                  backgroundColor: pn.color || "primary.main",
                },
              }}
            />
          ))}
        </Box>
      )}

      {/* System metrics */}
      <Typography
        variant="caption"
        sx={{
          fontFamily: "monospace",
          color: "text.secondary",
          whiteSpace: "nowrap",
          fontSize: "0.7rem",
        }}
      >
        CPU {Math.round(system?.cpuPercent ?? 0)}% · RAM{" "}
        {Math.round(system?.ramPercent ?? 0)}%
      </Typography>

      {/* Clock */}
      <Typography
        variant="body2"
        sx={{
          fontFamily: "monospace",
          color: "text.secondary",
          mx: 1,
          whiteSpace: "nowrap",
        }}
      >
        {clock}
      </Typography>

      {/* Volume control */}
      <VolumeControl store={store} />

      {/* Mic button (toggle: click to start, click again to stop) */}
      <IconButton
        size="small"
        onClick={handleMicToggle}
        sx={{ color: micActive ? "error.main" : "text.secondary" }}
      >
        {micActive ? <Stop fontSize="small" /> : <Mic fontSize="small" />}
      </IconButton>

      {/* Notification bell */}
      <NotificationBell />

      {/* Power button with dropdown */}
      <IconButton
        size="small"
        onClick={(e) => setAnchorEl(e.currentTarget)}
        sx={{ color: "text.secondary" }}
      >
        <PowerSettingsNew fontSize="small" />
      </IconButton>
      <Menu
        anchorEl={anchorEl}
        open={menuOpen}
        onClose={() => setAnchorEl(null)}
      >
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            reboot(store);
          }}
        >
          <ListItemIcon>
            <RestartAlt fontSize="small" />
          </ListItemIcon>
          <ListItemText>Reboot</ListItemText>
        </MenuItem>
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            powerOff(store);
          }}
        >
          <ListItemIcon>
            <PowerSettingsNew fontSize="small" />
          </ListItemIcon>
          <ListItemText>Power Off</ListItemText>
        </MenuItem>
      </Menu>
    </Box>
  );
}
