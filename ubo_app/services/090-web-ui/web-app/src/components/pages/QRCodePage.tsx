import { Box, Link, Paper } from "@mui/material";
import QRCode from "react-qr-code";

import type { StoreServiceClient } from "../../bindings/store/v1/StoreServiceClientPb";

interface QRCodePageProps {
  title: string;
  url: string;
  label?: string;
  store: StoreServiceClient;
}

export function QRCodePage({ title, url, label, store }: QRCodePageProps) {
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
        <Box
          sx={{
            backgroundColor: "white",
            p: 2,
            borderRadius: 1,
            display: "inline-flex",
          }}
        >
          <QRCode value={url} size={200} />
        </Box>
        <Link href={url} target="_blank" rel="noopener noreferrer">
          {label ?? url}
        </Link>
      </Paper>
    </Box>
  );
}
