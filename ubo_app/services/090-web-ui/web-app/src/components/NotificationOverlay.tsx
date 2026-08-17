import { Close, RecordVoiceOver } from "@mui/icons-material";
import {
  Box,
  Button,
  Card,
  CardContent,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { NotificationViewData } from "../bindings/ubo/v1/ubo_pb";
import { dismissNotification, executeAction } from "../store/action-dispatcher";
import { NOTIFICATION_DISMISS_PREFIX, NOTIFICATION_EXTRA_INFO_PREFIX } from "../store/constants";
import { unwrapItems } from "../store/helpers";
import { parseColoredIcon, stripColorMarkup } from "../utils/color-markup";

interface NotificationOverlayProps {
  data: NotificationViewData.AsObject;
  store: StoreServiceClient;
}

export function NotificationOverlay({
  data,
  store,
}: NotificationOverlayProps) {
  const items = unwrapItems(data.items?.itemsList);

  // Separate extra_info item from real action items and dismiss
  const extraInfoItem = items.find(
    (item) =>
      item.key === "extra_info" ||
      item.actionId?.startsWith(NOTIFICATION_EXTRA_INFO_PREFIX),
  );
  const actionItems = items.filter(
    (item) =>
      item.key !== "dismiss" &&
      item.key !== "extra_info" &&
      !item.actionId?.startsWith(NOTIFICATION_DISMISS_PREFIX) &&
      !item.actionId?.startsWith(NOTIFICATION_EXTRA_INFO_PREFIX),
  );
  const hasDismiss = items.some(
    (item) => item.key === "dismiss" || item.actionId?.startsWith(NOTIFICATION_DISMISS_PREFIX),
  );

  const [focusIndex, setFocusIndex] = useState(-1);
  const buttonRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    containerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (focusIndex >= 0 && focusIndex < buttonRefs.current.length) {
      buttonRefs.current[focusIndex]?.focus();
    }
  }, [focusIndex]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const total = actionItems.length;
      if (total === 0) return;

      switch (e.key) {
        case "ArrowRight": {
          e.preventDefault();
          setFocusIndex((prev) => (prev + 1) % total);
          break;
        }
        case "ArrowLeft": {
          e.preventDefault();
          setFocusIndex((prev) => (prev - 1 + total) % total);
          break;
        }
        case "ArrowUp": {
          e.preventDefault();
          const backBtn = document.querySelector<HTMLElement>("[data-back-button]");
          if (backBtn) {
            setFocusIndex(-1);
            backBtn.focus();
          }
          break;
        }
        case "Enter":
        case " ": {
          if (focusIndex >= 0 && focusIndex < total) {
            e.preventDefault();
            buttonRefs.current[focusIndex]?.click();
          }
          break;
        }
      }
    },
    [actionItems.length, focusIndex],
  );

  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: "100%",
        p: 2,
      }}
    >
      <Card
        sx={{
          maxWidth: 500,
          width: "100%",
          borderRadius: 3,
          borderLeft: 4,
          borderColor: data.color || "primary.main",
        }}
      >
        <CardContent>
          <Stack direction="row" alignItems="flex-start" spacing={1}>
            <Box sx={{ flex: 1 }}>
              {data.content && (
                <Typography variant="body2" color="text.secondary">
                  {stripColorMarkup(data.content)}
                </Typography>
              )}
              {data.extraInformation && (
                <Stack direction="row" alignItems="flex-start" spacing={1} sx={{ mt: 1 }}>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ flex: 1, fontFamily: "monospace" }}
                  >
                    {data.extraInformation}
                  </Typography>
                  {extraInfoItem?.actionId && (
                    <IconButton
                      size="small"
                      onClick={() => {
                        executeAction(store, extraInfoItem.actionId!);
                      }}
                      sx={{
                        backgroundColor: "primary.main",
                        color: "#fff",
                        width: 28,
                        height: 28,
                        flexShrink: 0,
                        "&:hover": {
                          backgroundColor: "primary.dark",
                        },
                      }}
                    >
                      <RecordVoiceOver sx={{ fontSize: 16 }} />
                    </IconButton>
                  )}
                </Stack>
              )}
              {/* Render real action buttons (QR code, Web UI, etc.) */}
              {actionItems.length > 0 && (
                <Box
                  data-notification-actions
                  sx={{
                    mt: 1,
                    display: "grid",
                    gridTemplateColumns: "repeat(2, 1fr)",
                    gap: 1,
                  }}
                  tabIndex={0}
                  ref={containerRef}
                  onKeyDown={handleKeyDown}
                >
                  {actionItems.map((item, index) => {
                    const parsedIcon = item.icon
                      ? parseColoredIcon(item.icon)
                      : null;
                    const label = item.label
                      ? stripColorMarkup(item.label)
                      : null;
                    const iconSpan = parsedIcon ? (
                      <span
                        style={{
                          fontFamily: "ArimoNerdFont",
                          fontSize: 16,
                        }}
                      >
                        {parsedIcon.icon}
                      </span>
                    ) : null;
                    return (
                      <Button
                        key={`${item.key || "action"}-${index}`}
                        ref={(el) => { buttonRefs.current[index] = el; }}
                        variant="contained"
                        size="small"
                        onClick={() => {
                          if (item.actionId) {
                            executeAction(store, item.actionId);
                          }
                        }}
                        sx={{
                          backgroundColor: "primary.main",
                          color: "#fff",
                          textTransform: "none",
                          borderRadius: 1,
                          px: 1.5,
                          py: 0.5,
                          minWidth: 0,
                          "&:hover": {
                            backgroundColor: "primary.dark",
                          },
                          "&:focus-visible": {
                            outline: "2px solid",
                            outlineColor: "primary.main",
                            outlineOffset: 2,
                          },
                        }}
                        startIcon={label ? iconSpan : undefined}
                      >
                        {/* Without a label the glyph becomes the body — it must
                            still render in the icon font, otherwise it shows as
                            a tofu box. */}
                        {label || iconSpan || "?"}
                      </Button>
                    );
                  })}
                </Box>
              )}
            </Box>
            {hasDismiss && (
              <IconButton
                size="small"
                onClick={() => dismissNotification(store, data.notificationId ?? "")}
                sx={{ mt: -0.5, color: "text.secondary" }}
              >
                <Close sx={{ fontSize: 18 }} />
              </IconButton>
            )}
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
