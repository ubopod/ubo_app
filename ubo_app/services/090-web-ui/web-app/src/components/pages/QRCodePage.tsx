import { ArrowBack } from "@mui/icons-material";
import { Box, IconButton, Link, Paper, Typography } from "@mui/material";
import QRCode from "react-qr-code";

import type { StoreServiceClient } from "../../bindings/store/v1/StoreServiceClientPb";
import { goBack } from "../../store/action-dispatcher";

interface QRCodePageProps {
  title: string;
  url: string;
  store: StoreServiceClient;
}

export function QRCodePage({ title, url, store }: QRCodePageProps) {
  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Box sx={{ display: "flex", alignItems: "center", mb: 2, gap: 1 }}>
        <IconButton size="small" onClick={() => goBack(store)}>
          <ArrowBack />
        </IconButton>
        <Typography variant="h6">{title}</Typography>
      </Box>
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
          {url}
        </Link>
      </Paper>
    </Box>
  );
}
