import { ArrowBack, Close, RecordVoiceOver } from "@mui/icons-material";
import {
  Box,
  Button,
  Card,
  CardContent,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";

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
            <IconButton
              size="small"
              onClick={() => dismissNotification(store, data.notificationId ?? "")}
              sx={{ mt: -0.5 }}
            >
              <ArrowBack />
            </IconButton>
            <Box sx={{ flex: 1 }}>
              <Typography variant="h6" gutterBottom>
                {stripColorMarkup(data.title ?? "")}
              </Typography>
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
                <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
                  {actionItems.map((item, index) => {
                    const parsedIcon = item.icon
                      ? parseColoredIcon(item.icon)
                      : null;
                    const label = item.label
                      ? stripColorMarkup(item.label)
                      : null;
                    return (
                      <Button
                        key={`${item.key || "action"}-${index}`}
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
                        }}
                        startIcon={
                          parsedIcon ? (
                            <span
                              style={{
                                fontFamily: "ArimoNerdFont",
                                fontSize: 16,
                              }}
                            >
                              {parsedIcon.icon}
                            </span>
                          ) : undefined
                        }
                      >
                        {label || parsedIcon?.icon || "?"}
                      </Button>
                    );
                  })}
                </Stack>
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
