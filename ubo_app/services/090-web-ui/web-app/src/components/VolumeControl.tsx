import {
  VolumeDown,
  VolumeMute,
  VolumeOff,
  VolumeUp,
} from "@mui/icons-material";
import { Box, IconButton, Popover, Slider, Typography } from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import { changeVolume, setVolume } from "../store/action-dispatcher";
import { useAppState } from "../store/useAppState";

interface VolumeControlProps {
  store: StoreServiceClient;
}

function VolumeIcon({ level }: { level: number }) {
  if (level === 0) return <VolumeOff fontSize="small" />;
  if (level < 0.33) return <VolumeMute fontSize="small" />;
  if (level < 0.67) return <VolumeDown fontSize="small" />;
  return <VolumeUp fontSize="small" />;
}

export function VolumeControl({ store }: VolumeControlProps) {
  const { volume } = useAppState();
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const open = Boolean(anchorEl);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const handleToggle = useCallback(
    (e: React.MouseEvent<HTMLElement>) => {
      setAnchorEl(open ? null : e.currentTarget);
    },
    [open],
  );

  const handleClose = useCallback(() => {
    setAnchorEl(null);
  }, []);

  const [localPercent, setLocalPercent] = useState<number | null>(null);

  const handleSliderChange = useCallback(
    (_: Event, value: number | number[]) => {
      setLocalPercent(value as number);
    },
    [],
  );

  const handleSliderCommit = useCallback(
    (_: Event | React.SyntheticEvent, value: number | number[]) => {
      const v = (value as number) / 100;
      setVolume(store, v);
      setLocalPercent(null);
    },
    [store],
  );

  // Keyboard handler for volume adjustment while popover is open
  useEffect(() => {
    if (!open) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "ArrowUp") {
        e.preventDefault();
        e.stopPropagation();
        changeVolume(store, 0.05);
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        e.stopPropagation();
        changeVolume(store, -0.05);
      } else if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        setAnchorEl(null);
      }
    }

    // Use capture phase to intercept before other handlers
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [open, store]);

  const percent = Math.round(volume * 100);

  return (
    <>
      <IconButton
        ref={buttonRef}
        size="small"
        onClick={handleToggle}
        sx={{ color: "text.secondary" }}
      >
        <VolumeIcon level={volume} />
      </IconButton>
      <Typography
        variant="caption"
        sx={{
          fontFamily: "monospace",
          color: "text.secondary",
          fontSize: "0.7rem",
          minWidth: "2.5em",
          textAlign: "right",
        }}
      >
        {percent}%
      </Typography>
      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
        transformOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Box
          sx={{
            height: 150,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            py: 2,
            px: 1,
          }}
        >
          <Slider
            orientation="vertical"
            value={localPercent ?? percent}
            onChange={handleSliderChange}
            onChangeCommitted={handleSliderCommit}
            min={0}
            max={100}
            sx={{ height: "100%" }}
          />
        </Box>
      </Popover>
    </>
  );
}
