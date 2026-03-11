import { ArrowBack, Close, RecordVoiceOver } from "@mui/icons-material";
import {
  Box,
  Card,
  CardContent,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { NotificationViewData } from "../bindings/ubo/v1/ubo_pb";
import { dismissNotification, executeAction } from "../store/action-dispatcher";
import { NOTIFICATION_DISMISS_PREFIX } from "../store/constants";
import { unwrapItems } from "../store/helpers";
import { stripColorMarkup } from "../utils/color-markup";

interface NotificationOverlayProps {
  data: NotificationViewData.AsObject;
  store: StoreServiceClient;
}

export function NotificationOverlay({
  data,
  store,
}: NotificationOverlayProps) {
  const items = unwrapItems(data.items?.itemsList);

  // Separate dismiss actions from other actions (e.g. read-aloud)
  const actionItems = items.filter(
    (item) => item.key !== "dismiss" && !item.actionId?.startsWith(NOTIFICATION_DISMISS_PREFIX),
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
                  {actionItems.length > 0 && (
                    <IconButton
                      size="small"
                      onClick={() => {
                        if (actionItems[0].actionId) {
                          executeAction(store, actionItems[0].actionId);
                        }
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
              {/* Show action buttons when there's no extra information to attach them to */}
              {!data.extraInformation && actionItems.length > 0 && (
                <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                  {actionItems.map((item, index) => (
                    <IconButton
                      key={`${item.key || "item"}-${index}`}
                      size="small"
                      onClick={() => {
                        if (item.actionId) {
                          executeAction(store, item.actionId);
                        }
                      }}
                      sx={{
                        backgroundColor: "primary.main",
                        color: "#fff",
                        width: 28,
                        height: 28,
                        "&:hover": {
                          backgroundColor: "primary.dark",
                        },
                      }}
                    >
                      <RecordVoiceOver sx={{ fontSize: 16 }} />
                    </IconButton>
                  ))}
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
