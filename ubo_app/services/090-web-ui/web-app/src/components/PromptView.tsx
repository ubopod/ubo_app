import { Box, Button, Paper, Stack, Typography } from "@mui/material";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { PromptViewData } from "../bindings/ubo/v1/ubo_pb";
import { executeAction } from "../store/action-dispatcher";

export function PromptView({
  data,
  store,
}: {
  data: PromptViewData.AsObject;
  store: StoreServiceClient;
}) {
  const items = data.items?.itemsList ?? [];

  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Paper
        sx={{
          p: 3,
          borderRadius: 2,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 3,
        }}
      >
        {data.prompt && (
          <Typography variant="h6" sx={{ textAlign: "center" }}>
            {data.prompt}
          </Typography>
        )}
        {items.length > 0 && (
          <Stack direction="row" spacing={2}>
            {items.map((item) => (
              <Button
                key={item.key}
                variant="contained"
                onClick={() => {
                  if (item.actionId) {
                    executeAction(store, item.actionId);
                  }
                }}
              >
                {item.label}
              </Button>
            ))}
          </Stack>
        )}
      </Paper>
    </Box>
  );
}
