import { Box, Link, Paper, Typography } from "@mui/material";
import QRCode from "react-qr-code";

interface QRCodePageProps {
  url: string;
  label?: string;
  // Optional line rendered under the link, for text that belongs with the code
  // but is not part of it — e.g. a device code the user has to type after
  // scanning. Kept out of the <Link> so it is not presented as clickable.
  caption?: string;
}

export function QRCodePage({ url, label, caption }: QRCodePageProps) {
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
        {caption ? (
          <Typography
            variant="h6"
            sx={{ fontFamily: "monospace", letterSpacing: "0.1em" }}
          >
            {caption}
          </Typography>
        ) : null}
      </Paper>
    </Box>
  );
}
