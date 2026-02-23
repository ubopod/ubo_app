import { Notifications } from "@mui/icons-material";
import {
  Badge,
  Box,
  ClickAwayListener,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Popper,
  Typography,
} from "@mui/material";
import { useCallback, useRef, useState } from "react";

import { useAppState } from "../store/useAppState";

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLButtonElement>(null);
  const { currentView } = useAppState();

  // Count notifications from current view if it's a notification type
  const notificationCount = currentView?.notificationViewData ? 1 : 0;

  const handleToggle = useCallback(() => {
    setOpen((prev) => !prev);
  }, []);

  const handleClose = useCallback(() => {
    setOpen(false);
  }, []);

  return (
    <>
      <IconButton
        ref={anchorRef}
        size="small"
        onClick={handleToggle}
        sx={{ color: "text.secondary" }}
      >
        <Badge badgeContent={notificationCount} color="error" variant="dot">
          <Notifications fontSize="small" />
        </Badge>
      </IconButton>
      <Popper
        open={open}
        anchorEl={anchorRef.current}
        placement="bottom-end"
        sx={{ zIndex: 1300 }}
      >
        <ClickAwayListener onClickAway={handleClose}>
          <Paper
            elevation={8}
            sx={{
              width: 300,
              maxHeight: 400,
              overflow: "auto",
              mt: 1,
              borderRadius: 2,
            }}
          >
            <Box sx={{ p: 1.5, borderBottom: 1, borderColor: "divider" }}>
              <Typography variant="subtitle2">Notifications</Typography>
            </Box>
            <List dense disablePadding>
              {notificationCount === 0 ? (
                <ListItemButton disabled>
                  <ListItemText
                    primary="No notifications"
                    sx={{ textAlign: "center" }}
                  />
                </ListItemButton>
              ) : (
                currentView?.notificationViewData && (
                  <ListItemButton onClick={handleClose}>
                    <ListItemText
                      primary={currentView.notificationViewData.title}
                      secondary={currentView.notificationViewData.content}
                    />
                  </ListItemButton>
                )
              )}
            </List>
          </Paper>
        </ClickAwayListener>
      </Popper>
    </>
  );
}
