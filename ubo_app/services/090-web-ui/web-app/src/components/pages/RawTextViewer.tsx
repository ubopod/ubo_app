import { Box, Paper, Typography } from "@mui/material";

import type { ApplicationPageProps } from "./types";

function getExtraString(
  data: ApplicationPageProps["data"],
  key: string,
): string {
  const entry = data.extraData?.itemsMap?.find(([k]) => k === key);
  if (!entry) return "";
  return entry[1].basicType?.string ?? "";
}

export function RawTextViewer({ data }: ApplicationPageProps) {
  const text = getExtraString(data, "text");

  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Paper
        sx={{
          p: 2,
          borderRadius: 2,
          maxHeight: "70vh",
          overflow: "auto",
        }}
      >
        <Typography
          component="pre"
          variant="body2"
          sx={{
            fontFamily: "monospace",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            m: 0,
            fontSize: "0.8rem",
            lineHeight: 1.5,
          }}
        >
          {text}
        </Typography>
      </Paper>
    </Box>
  );
}
