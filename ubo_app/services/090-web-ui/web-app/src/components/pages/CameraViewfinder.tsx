import { Box } from "@mui/material";
import { useEffect, useRef } from "react";

import { CameraReportImageEvent, Event } from "../../bindings/ubo/v1/ubo_pb";
import type { SubscribeEventResponse } from "../../bindings/store/v1/store_pb";
import { subscribeToEvents } from "../../store/audio";
import { registerPageStream } from "../../store/action-dispatcher";
import type { ApplicationPageProps } from "./types";

export function CameraViewfinder({ store }: ApplicationPageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let frameId: number | null = null;
    let pendingFrame: { data: Uint8Array; width: number; height: number } | null = null;

    const unsubscribe = subscribeToEvents(
      store,
      [(event: Event) =>
        event.setCameraReportImageEvent(new CameraReportImageEvent())],
      (response: SubscribeEventResponse) => {
        const cameraEvent = response
          .getEvent()
          ?.getCameraReportImageEvent();
        if (!cameraEvent) return;

        const rgb = cameraEvent.getData_asU8();
        const width = cameraEvent.getWidth();
        const height = cameraEvent.getHeight();

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

            // Convert RGB to RGBA
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

    // Register so dispatch() can cancel this stream to free a connection slot
    const unregister = registerPageStream(unsubscribe);

    return () => {
      unregister();
      unsubscribe();
      if (frameId !== null) cancelAnimationFrame(frameId);
    };
  }, [store]);

  return (
    <Box sx={{ width: "100%", p: 2 }}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "center",
          backgroundColor: "black",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <canvas
          ref={canvasRef}
          style={{
            maxWidth: "100%",
            height: "auto",
            display: "block",
          }}
        />
      </Box>
    </Box>
  );
}
