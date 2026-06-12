import { ArrowBack, ArrowForward } from "@mui/icons-material";
import FitScreenIcon from "@mui/icons-material/FitScreen";
import ZoomInIcon from "@mui/icons-material/ZoomIn";
import ZoomOutIcon from "@mui/icons-material/ZoomOut";
import {
  Box,
  Button,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SubscribeEventResponse } from "../bindings/store/v1/store_pb";
import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import {
  Event,
  FrameStreamDataEvent,
  type RenderViewData,
} from "../bindings/ubo/v1/ubo_pb";
import { registerPageStream } from "../store/action-dispatcher";
import { subscribeToEvents } from "../store/audio";
import { QRCodePage } from "./pages/QRCodePage";

interface RenderViewProps {
  data: RenderViewData.AsObject;
  store: StoreServiceClient;
}

function propEntry(data: RenderViewData.AsObject, key: string) {
  return data.props?.itemsMap?.find(([entryKey]) => entryKey === key);
}

function propString(data: RenderViewData.AsObject, key: string): string {
  return propEntry(data, key)?.[1].basicType?.string ?? "";
}

function propNumber(data: RenderViewData.AsObject, key: string): number {
  const value = propEntry(data, key)?.[1].basicType;
  return value?.int64 ?? value?.pb_float ?? 0;
}

function bytesToRgb(bytes: Uint8Array | string | undefined): Uint8Array | null {
  if (!bytes) return null;
  if (bytes instanceof Uint8Array) return bytes;
  const binary = atob(bytes);
  const arr = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    arr[i] = binary.charCodeAt(i);
  }
  return arr;
}

function propStringList(data: RenderViewData.AsObject, key: string): string[] {
  return (
    propEntry(data, key)?.[1].list?.itemsList
      ?.map((item) => item.string)
      .filter(Boolean) ?? []
  );
}

function StatusRender({ data }: { data: RenderViewData.AsObject }) {
  const text = propString(data, "text");
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
        <Typography variant="body1">{text}</Typography>
      </Paper>
    </Box>
  );
}

function QRCodeCarousel({ data }: RenderViewProps) {
  const [index, setIndex] = useState(0);
  const values = propStringList(data, "values");
  const labels = propStringList(data, "labels");
  const value = values[index] ?? "";
  const label = labels[index] ?? value;

  return (
    <Box>
      <QRCodePage url={value} label={label} />
      {values.length > 1 && (
        <Box sx={{ display: "flex", justifyContent: "center", gap: 1, mt: 1 }}>
          <Button
            size="small"
            startIcon={<ArrowBack />}
            disabled={index === 0}
            onClick={() => setIndex((i) => i - 1)}
          >
            Prev IP
          </Button>
          <Button
            size="small"
            endIcon={<ArrowForward />}
            disabled={index === values.length - 1}
            onClick={() => setIndex((i) => i + 1)}
          >
            Next IP
          </Button>
        </Box>
      )}
    </Box>
  );
}

function TextViewer({ data }: { data: RenderViewData.AsObject }) {
  const text = propString(data, "text");
  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Paper sx={{ p: 2, borderRadius: 2, maxHeight: "70vh", overflow: "auto" }}>
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

const ZOOM_FACTOR = 1.3;
const MIN_ZOOM = 0.05;
const MAX_ZOOM = 20;

function ImageViewer({ data }: { data: RenderViewData.AsObject }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState<number | null>(null);
  const fittedRef = useRef(false);
  // Memoise on the raw (stable) bytes value so the decode + redraw effect
  // only fires when the image actually changes — not on every re-render
  // (bytesToRgb decodes base64 into a fresh array each call). This is what
  // lets an in-place image_viewer update (same stack item, new picture)
  // repaint the canvas instead of showing the first image forever.
  const rawImage = propEntry(data, "image")?.[1].basicType?.bytes;
  const rgb = useMemo(() => bytesToRgb(rawImage), [rawImage]);
  const width = propNumber(data, "width");
  const height = propNumber(data, "height");

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !rgb || width === 0 || height === 0) return;
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
    // Fit to screen once (on the first painted frame), then preserve the
    // user's chosen zoom across subsequent in-place image updates.
    if (!fittedRef.current) {
      fittedRef.current = true;
      const container = containerRef.current;
      if (container) {
        setZoom(Math.min(container.clientWidth / width, (window.innerHeight * 0.7) / height));
      }
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
      setZoom(Math.min(container.clientWidth / width, (window.innerHeight * 0.7) / height));
    }
  }, [width, height]);
  const displayZoom = zoom ?? 1;

  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Stack direction="row" justifyContent="center" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <IconButton size="small" onClick={zoomOut}><ZoomOutIcon /></IconButton>
        <Typography variant="body2" sx={{ minWidth: 48, textAlign: "center" }}>
          {Math.round(displayZoom * 100)}%
        </Typography>
        <IconButton size="small" onClick={zoomIn}><ZoomInIcon /></IconButton>
        <IconButton size="small" onClick={fitToScreen}><FitScreenIcon /></IconButton>
      </Stack>
      <Box
        ref={containerRef}
        onWheel={(e) => {
          e.preventDefault();
          if (e.deltaY < 0) zoomIn();
          else zoomOut();
        }}
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

function FrameStream({ data, store }: RenderViewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let frameId: number | null = null;
    let pendingFrame: { data: Uint8Array; width: number; height: number } | null = null;

    const unsubscribe = subscribeToEvents(
      store,
      [(event: Event) => event.setFrameStreamDataEvent(new FrameStreamDataEvent())],
      (response: SubscribeEventResponse) => {
        const frameEvent = response.getEvent()?.getFrameStreamDataEvent();
        if (!frameEvent || frameEvent.getStreamId() !== data.streamId) return;
        const rgb = frameEvent.getData_asU8();
        const width = frameEvent.getWidth();
        const height = frameEvent.getHeight();
        if (rgb.length === 0 || width === 0 || height === 0) return;
        pendingFrame = { data: rgb, width, height };
        if (frameId === null) {
          frameId = requestAnimationFrame(() => {
            frameId = null;
            if (!pendingFrame) return;
            const canvas = canvasRef.current;
            if (!canvas) return;
            const { data, width, height } = pendingFrame;
            pendingFrame = null;
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext("2d");
            if (!ctx) return;
            const rgba = new Uint8ClampedArray(width * height * 4);
            for (let i = 0, j = 0; i < data.length; i += 3, j += 4) {
              rgba[j] = data[i];
              rgba[j + 1] = data[i + 1];
              rgba[j + 2] = data[i + 2];
              rgba[j + 3] = 255;
            }
            ctx.putImageData(new ImageData(rgba, width, height), 0, 0);
          });
        }
      },
    );
    const unregister = registerPageStream(unsubscribe);
    return () => {
      unregister();
      unsubscribe();
      if (frameId !== null) cancelAnimationFrame(frameId);
    };
  }, [data.streamId, store]);

  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Box sx={{ display: "flex", justifyContent: "center", backgroundColor: "black", borderRadius: 2, overflow: "hidden" }}>
        <canvas ref={canvasRef} style={{ maxWidth: "100%", height: "auto", display: "block" }} />
      </Box>
    </Box>
  );
}

export function RenderView({ data, store }: RenderViewProps) {
  switch (data.kind) {
    case "qr_code":
      return (
        <QRCodePage
          url={propString(data, "value")}
          label={propString(data, "label") || propString(data, "value")}
        />
      );
    case "qr_code_carousel":
      return <QRCodeCarousel data={data} store={store} />;
    case "status":
      return <StatusRender data={data} />;
    case "text_viewer":
      return <TextViewer data={data} />;
    case "image_viewer":
      return <ImageViewer data={data} />;
    case "frame_stream":
      return <FrameStream data={data} store={store} />;
    default:
      return <TextViewer data={{ ...data, props: undefined }} />;
  }
}
