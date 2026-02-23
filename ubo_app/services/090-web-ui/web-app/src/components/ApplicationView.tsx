import { ArrowBack } from "@mui/icons-material";
import { Box, IconButton, Paper, Typography } from "@mui/material";

import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import type { ApplicationViewData } from "../bindings/ubo/v1/ubo_pb";
import { goBack } from "../store/action-dispatcher";

interface ApplicationViewProps {
  data: ApplicationViewData.AsObject;
  store: StoreServiceClient;
}

export function ApplicationView({ data, store }: ApplicationViewProps) {
  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Box sx={{ display: "flex", alignItems: "center", mb: 2, gap: 1 }}>
        <IconButton size="small" onClick={() => goBack(store)}>
          <ArrowBack />
        </IconButton>
        <Typography variant="h6">
          {data.applicationId || "Application"}
        </Typography>
      </Box>
      <Paper sx={{ p: 3, borderRadius: 2, textAlign: "center" }}>
        <Typography variant="body2" color="text.secondary">
          Application: {data.applicationId}
        </Typography>
        {data.extraData?.itemsMap && (
          <Box sx={{ mt: 2, textAlign: "left" }}>
            {data.extraData.itemsMap.map(([key, value]) => (
              <Typography
                key={key}
                variant="body2"
                sx={{ fontFamily: "monospace" }}
              >
                {key}: {value}
              </Typography>
            ))}
          </Box>
        )}
      </Paper>
    </Box>
  );
}
