import { ArrowBack, ArrowForward } from "@mui/icons-material";
import { Box, Button } from "@mui/material";
import { useState } from "react";

import { extractBasicValue } from "../ApplicationView";
import { QRCodePage } from "./QRCodePage";
import type { ApplicationPageProps } from "./types";

export function DockerQRCodePage({ data, store }: ApplicationPageProps) {
  const [ipIndex, setIpIndex] = useState(0);

  const extraMap = data.extraData?.itemsMap ?? [];

  const ipsEntry = extraMap.find(([key]) => key === "ips");
  const portEntry = extraMap.find(([key]) => key === "port");

  let ips: string[] = [];
  if (ipsEntry) {
    const listItems = ipsEntry[1]?.list?.itemsList;
    if (listItems) {
      ips = listItems.map((item) => extractBasicValue(item)).filter(Boolean);
    }
  }

  const port = portEntry ? extractBasicValue(portEntry[1]?.basicType) : "";

  const currentIp = ips[ipIndex] ?? "localhost";
  const url = `http://${currentIp}:${port}/`;

  return (
    <Box>
      <QRCodePage title="Docker Port" url={url} store={store} />
      {ips.length > 1 && (
        <Box sx={{ display: "flex", justifyContent: "center", gap: 1, mt: 1 }}>
          <Button
            size="small"
            startIcon={<ArrowBack />}
            disabled={ipIndex === 0}
            onClick={() => setIpIndex((i) => i - 1)}
          >
            Prev IP
          </Button>
          <Button
            size="small"
            endIcon={<ArrowForward />}
            disabled={ipIndex === ips.length - 1}
            onClick={() => setIpIndex((i) => i + 1)}
          >
            Next IP
          </Button>
        </Box>
      )}
    </Box>
  );
}
