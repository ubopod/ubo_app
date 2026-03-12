import {
  FiberManualRecord,
  Mic,
  PowerSettingsNew,
  RestartAlt,
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
  const { cpuPercent, ramPercent } = useAppState();
  const icons = data?.icons?.itemsList ?? [];
  const progressNotifications =
    data?.progressNotifications?.itemsList ?? [];
  const clock = data?.clock ?? "";

  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const menuOpen = Boolean(anchorEl);
  const [micActive, setMicActive] = useState(isBrowserMicActive());

  const handleMicDown = useCallback(() => {
    startBrowserMic(store).then(() => setMicActive(true));
  }, [store]);

  const handleMicUp = useCallback(() => {
    stopBrowserMic(store);
    setMicActive(false);
  }, [store]);

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
        CPU {Math.round(cpuPercent)}% · RAM {Math.round(ramPercent)}%
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

      {/* Mic button (push-to-talk) */}
      <IconButton
        size="small"
        onMouseDown={handleMicDown}
        onMouseUp={handleMicUp}
        onMouseLeave={micActive ? handleMicUp : undefined}
        onTouchStart={handleMicDown}
        onTouchEnd={handleMicUp}
        sx={{ color: micActive ? "error.main" : "text.secondary" }}
      >
        <Mic fontSize="small" />
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
