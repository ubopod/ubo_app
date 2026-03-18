import { Box, CircularProgress, Paper, Typography } from "@mui/material";

import { extractBasicValue } from "../ApplicationView";
import { QRCodePage } from "./QRCodePage";
import type { ApplicationPageProps } from "./types";

export function RPiConnectSignInPage({ data, store }: ApplicationPageProps) {
  const extraMap = data.extraData?.itemsMap ?? [];
  const stageEntry = extraMap.find(([key]) => key === "stage");
  const stage = stageEntry ? extractBasicValue(stageEntry[1]?.basicType) : "0";
  const urlEntry = extraMap.find(([key]) => key === "url");
  const url = urlEntry ? extractBasicValue(urlEntry[1]?.basicType) : "";

  if (stage === "1" && url) {
    return <QRCodePage title="RPi Connect Sign In" url={url} store={store} />;
  }

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
        <CircularProgress size={40} />
        <Typography variant="body1">Logging in...</Typography>
      </Paper>
    </Box>
  );
}
