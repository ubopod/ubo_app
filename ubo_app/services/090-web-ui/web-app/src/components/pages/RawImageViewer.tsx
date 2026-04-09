import { Box, IconButton, Stack, Typography } from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";
import ZoomInIcon from "@mui/icons-material/ZoomIn";
import ZoomOutIcon from "@mui/icons-material/ZoomOut";
import FitScreenIcon from "@mui/icons-material/FitScreen";

import type { ApplicationPageProps } from "./types";

function getExtraBytes(
  data: ApplicationPageProps["data"],
  key: string,
): Uint8Array | null {
  const entry = data.extraData?.itemsMap?.find(([k]) => k === key);
  if (!entry) return null;
  const bytes = entry[1].basicType?.bytes;
  if (!bytes) return null;
  if (bytes instanceof Uint8Array) return bytes;
  const binary = atob(bytes);
  const arr = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    arr[i] = binary.charCodeAt(i);
  }
  return arr;
}

function getExtraNumber(
  data: ApplicationPageProps["data"],
  key: string,
): number {
  const entry = data.extraData?.itemsMap?.find(([k]) => k === key);
  if (!entry) return 0;
  return entry[1].basicType?.int64 ?? 0;
}

const ZOOM_FACTOR = 1.3;
const MIN_ZOOM = 0.05;
const MAX_ZOOM = 20;

export function RawImageViewer({ data }: ApplicationPageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState<number | null>(null);
  const drawnRef = useRef(false);

  const rgb = getExtraBytes(data, "image");
  const width = getExtraNumber(data, "width");
  const height = getExtraNumber(data, "height");

  // Draw image to canvas once
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !rgb || width === 0 || height === 0 || drawnRef.current) return;

    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const rgba = new Uint8ClampedArray(width * height * 4);
    for (let i = 0, j = 0; i < rgb.length; i += 3, j += 4) {
      rgba[j] = rgb[i];
      rgba[j + 1] = rgb[i + 1];
      rgba[j + 2] = rgb[i + 2];
      rgba[j + 3] = 255;
    }

    ctx.putImageData(new ImageData(rgba, width, height), 0, 0);
    drawnRef.current = true;

    // Set initial zoom to fit container
    const container = containerRef.current;
    if (container) {
      const fit = Math.min(
        container.clientWidth / width,
        (window.innerHeight * 0.7) / height,
      );
      setZoom(fit);
    }
  }, [rgb, width, height]);

  const zoomIn = useCallback(() => {
    setZoom((z) => Math.min((z ?? 1) * ZOOM_FACTOR, MAX_ZOOM));
  }, []);

  const zoomOut = useCallback(() => {
    setZoom((z) => Math.max((z ?? 1) / ZOOM_FACTOR, MIN_ZOOM));
  }, []);

  const fitToScreen = useCallback(() => {
    const container = containerRef.current;
    if (container && width && height) {
      setZoom(
        Math.min(
          container.clientWidth / width,
          (window.innerHeight * 0.7) / height,
        ),
      );
    }
  }, [width, height]);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      if (e.deltaY < 0) zoomIn();
      else zoomOut();
    },
    [zoomIn, zoomOut],
  );

  const displayZoom = zoom ?? 1;
  const pct = Math.round(displayZoom * 100);

  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Stack direction="row" justifyContent="center" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <IconButton size="small" onClick={zoomOut}>
          <ZoomOutIcon />
        </IconButton>
        <Typography variant="body2" sx={{ minWidth: 48, textAlign: "center" }}>
          {pct}%
        </Typography>
        <IconButton size="small" onClick={zoomIn}>
          <ZoomInIcon />
        </IconButton>
        <IconButton size="small" onClick={fitToScreen}>
          <FitScreenIcon />
        </IconButton>
      </Stack>
      <Box
        ref={containerRef}
        onWheel={handleWheel}
        sx={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          backgroundColor: "black",
          borderRadius: 2,
          overflow: "auto",
          maxHeight: "70vh",
        }}
      >
        <canvas
          ref={canvasRef}
          style={{
            width: `${width * displayZoom}px`,
            height: `${height * displayZoom}px`,
            display: "block",
            imageRendering: displayZoom > 2 ? "pixelated" : "auto",
          }}
        />
      </Box>
    </Box>
  );
}
