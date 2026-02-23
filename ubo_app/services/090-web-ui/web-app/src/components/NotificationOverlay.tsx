import { ArrowBack } from "@mui/icons-material";
import {
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { NotificationViewData } from "../bindings/ubo/v1/ubo_pb";
import { dismissNotification, executeAction } from "../store/action-dispatcher";
import { unwrapItems } from "../store/helpers";
import { parseKivyIcon, stripKivyMarkup } from "../utils/kivy-markup";

interface NotificationOverlayProps {
  data: NotificationViewData.AsObject;
  store: StoreServiceClient;
}

export function NotificationOverlay({
  data,
  store,
}: NotificationOverlayProps) {
  const items = unwrapItems(data.items?.itemsList);

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
            <IconButton size="small" onClick={() => dismissNotification(store, data.notificationId ?? "")}>
              <ArrowBack />
            </IconButton>
            <Box sx={{ flex: 1 }}>
              {data.icon && (() => {
                const parsed = parseKivyIcon(data.icon!);
                return (
                  <Typography
                    sx={{
                      fontFamily: "ArimoNerdFont",
                      fontSize: 32,
                      color: parsed.color || data.color || "primary.main",
                      mb: 1,
                    }}
                  >
                    {parsed.icon}
                  </Typography>
                );
              })()}
              <Typography variant="h6" gutterBottom>
                {stripKivyMarkup(data.title ?? "")}
              </Typography>
              {data.content && (
                <Typography variant="body2" color="text.secondary">
                  {stripKivyMarkup(data.content)}
                </Typography>
              )}
              {data.extraInformation && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ mt: 1, display: "block", fontFamily: "monospace" }}
                >
                  {data.extraInformation}
                </Typography>
              )}
            </Box>
          </Stack>
        </CardContent>
        {items.length > 0 && (
          <CardActions sx={{ px: 2, pb: 2, flexWrap: "wrap", gap: 1 }}>
            {items.map((item, index) => (
              <Button
                key={item.key || index}
                variant="outlined"
                size="small"
                onClick={() => {
                  if (item.actionId) {
                    executeAction(store, item.actionId);
                  }
                }}
                sx={{
                  color: item.color || undefined,
                  borderColor: item.color || undefined,
                }}
              >
                {item.label}
              </Button>
            ))}
          </CardActions>
        )}
      </Card>
    </Box>
  );
}
