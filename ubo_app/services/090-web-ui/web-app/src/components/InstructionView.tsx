import { Box, CircularProgress, Paper, Typography } from "@mui/material";

import type { InstructionViewData } from "../bindings/ubo/v1/ubo_pb";

export function InstructionView({
  data,
}: {
  data: InstructionViewData.AsObject;
}) {
  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Paper
        sx={{
          p: 3,
          borderRadius: 2,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 2,
        }}
      >
        {data.spinner && <CircularProgress size={40} />}
        {data.instruction && (
          <Typography variant="body1" sx={{ textAlign: "center" }}>
            {data.instruction}
          </Typography>
        )}
        {data.progressText && (
          <Typography variant="body2" color="text.secondary">
            {data.progressText}
          </Typography>
        )}
        {data.footerText && (
          <Typography variant="caption" color="text.secondary">
            {data.footerText}
          </Typography>
        )}
      </Paper>
    </Box>
  );
}
