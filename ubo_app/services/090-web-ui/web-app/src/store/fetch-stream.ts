/**
 * gRPC-web server streaming over `fetch` + `ReadableStream`.
 *
 * The generated `StoreServiceClient` cannot carry a long-lived stream. grpc-web
 * supports server streaming only in `grpcwebtext` mode, and its one transport is
 * `XMLHttpRequest`: on every chunk the reader takes the whole
 * `xhr.responseText` and slices off the part it has not parsed yet. The browser
 * keeps that string alive for as long as the request is open, so a stream that
 * never ends grows the renderer's heap without bound. On the device kiosk that
 * ends with the renderer being OOM-killed and the screen stuck on "Aw, Snap".
 *
 * Reading the body as a stream instead lets each chunk be dropped as soon as it
 * has been parsed, so memory stays flat however long the stream runs — only the
 * frame currently being assembled is retained. The wire format is the binary
 * one (`application/grpc-web+proto`), which Envoy's `grpc_web` filter speaks
 * without any configuration change.
 *
 * Frames are `[flags:1][length:4 big-endian][payload:length]`. A frame with
 * {@link TRAILER_FLAG} set carries the trailing metadata (`grpc-status`,
 * `grpc-message`) as CRLF-separated header lines rather than a message.
 */

const FRAME_HEADER_SIZE = 5;
const TRAILER_FLAG = 0x80;
const CONTENT_TYPE = "application/grpc-web+proto";

export interface StreamSink<RESP> {
  onData: (message: RESP) => void;
  /**
   * Called exactly once when the stream stops, with an error if it failed.
   *
   * Not called at all for a stream stopped through {@link Cancelable.cancel},
   * so disposing cannot be mistaken for a disconnect.
   */
  onEnd: (error?: Error) => void;
}

export interface Cancelable {
  cancel(): void;
}

export interface ServerStreamOptions<REQ, RESP> {
  url: string;
  request: REQ;
  deserialize: (bytes: Uint8Array) => RESP;
  sink: StreamSink<RESP>;
}

/**
 * A byte queue that retains only the frame being assembled.
 *
 * Chunks are dropped as they are consumed rather than concatenated into one
 * growing buffer, which is the whole point of this module — a single buffer
 * would reproduce exactly the leak we are here to remove.
 */
class ChunkQueue {
  private chunks: Uint8Array[] = [];
  private offset = 0;
  private available = 0;

  push(chunk: Uint8Array): void {
    if (chunk.length === 0) return;
    this.chunks.push(chunk);
    this.available += chunk.length;
  }

  get size(): number {
    return this.available;
  }

  /** Remove and return exactly `count` bytes, or `null` if fewer are buffered. */
  take(count: number): Uint8Array | null {
    if (this.available < count) return null;

    const out = new Uint8Array(count);
    let written = 0;
    while (written < count) {
      const head = this.chunks[0];
      const size = Math.min(count - written, head.length - this.offset);
      out.set(head.subarray(this.offset, this.offset + size), written);
      written += size;
      this.offset += size;
      if (this.offset === head.length) {
        this.chunks.shift();
        this.offset = 0;
      }
    }
    this.available -= count;
    return out;
  }
}

function frameRequest(payload: Uint8Array): Uint8Array {
  const frame = new Uint8Array(FRAME_HEADER_SIZE + payload.length);
  // frame[0] stays 0: a data frame, uncompressed.
  new DataView(frame.buffer).setUint32(1, payload.length, false);
  frame.set(payload, FRAME_HEADER_SIZE);
  return frame;
}

function parseTrailers(payload: Uint8Array): Record<string, string> {
  const trailers: Record<string, string> = {};
  for (const line of new TextDecoder().decode(payload).split("\r\n")) {
    const separator = line.indexOf(":");
    if (separator === -1) continue;
    trailers[line.slice(0, separator).trim().toLowerCase()] = line
      .slice(separator + 1)
      .trim();
  }
  return trailers;
}

function statusError(
  status: string | null | undefined,
  message: string | null | undefined,
): Error | undefined {
  if (status == null || status === "0") return undefined;
  return new Error(`gRPC status ${status}${message ? `: ${message}` : ""}`);
}

/**
 * Open a server-streaming gRPC-web call.
 *
 * @param url Fully qualified method URL, e.g. `<base>/pkg.Service/Method`.
 * @param request Protobuf request message to send.
 * @param deserialize Decoder for a single response message.
 * @param sink Receives every message, then a single termination callback.
 */
export function openServerStream<
  REQ extends { serializeBinary(): Uint8Array },
  RESP,
>({
  url,
  request,
  deserialize,
  sink,
}: ServerStreamOptions<REQ, RESP>): Cancelable {
  const controller = new AbortController();
  let settled = false;

  const settle = (error?: Error): void => {
    if (settled) return;
    settled = true;
    sink.onEnd(error);
  };

  void (async () => {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "content-type": CONTENT_TYPE,
          accept: CONTENT_TYPE,
          "x-grpc-web": "1",
        },
        body: frameRequest(request.serializeBinary()),
        signal: controller.signal,
      });

      if (!response.ok) {
        settle(new Error(`gRPC-web request failed with HTTP ${response.status}`));
        return;
      }

      // A trailers-only response puts the status in the HTTP headers and sends
      // no body — how Envoy answers an RPC that fails before its first message.
      const headerError = statusError(
        response.headers.get("grpc-status"),
        response.headers.get("grpc-message"),
      );
      if (headerError) {
        settle(headerError);
        return;
      }

      if (!response.body) {
        settle(new Error("gRPC-web response carried no body"));
        return;
      }

      const reader = response.body.getReader();
      const queue = new ChunkQueue();
      let header: { trailer: boolean; length: number } | null = null;
      let trailerError: Error | undefined;

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        queue.push(value);

        // Drain every whole frame the new chunk completed. Partial frames stay
        // in the queue until the bytes that finish them arrive.
        for (;;) {
          if (!header) {
            const bytes = queue.take(FRAME_HEADER_SIZE);
            if (!bytes) break;
            header = {
              trailer: (bytes[0] & TRAILER_FLAG) !== 0,
              length: new DataView(bytes.buffer).getUint32(1, false),
            };
          }

          const payload = queue.take(header.length);
          if (!payload) break;
          const isTrailer = header.trailer;
          header = null;

          if (isTrailer) {
            const trailers = parseTrailers(payload);
            trailerError = statusError(
              trailers["grpc-status"],
              trailers["grpc-message"],
            );
          } else {
            sink.onData(deserialize(payload));
          }
        }
      }

      settle(trailerError);
    } catch (error) {
      // `cancel()` aborts the fetch, which rejects the pending read. That is a
      // disposal, not a failure, and must not look like a disconnect.
      if (controller.signal.aborted) return;
      settle(error instanceof Error ? error : new Error(String(error)));
    }
  })();

  return {
    cancel(): void {
      settled = true;
      controller.abort();
    },
  };
}
