import type { ClientReadableStream } from "grpc-web";

// Retry delay after a stream terminates. Matches the interval the hand-rolled
// subscriptions used before this helper existed.
const RETRY_DELAY_MS = 1000;

export interface ResilientStream {
  /**
   * Cancel the live stream and stop reconnecting, permanently.
   *
   * Safe to call at any point, including while a retry is pending.
   */
  dispose(): void;
}

/**
 * A gRPC-web server-streaming subscription that reconnects on its own and can
 * actually be shut down.
 *
 * Two things here are load-bearing and are easy to get wrong by hand:
 *
 * 1. **Both `error` and `end` mean "terminated".** grpc-web only emits `end`
 *    when a stream closes with an OK status — which is exactly what a graceful
 *    server shutdown produces — so retrying on `error` alone leaves the page
 *    permanently disconnected after a restart.
 *
 * 2. **`error` and `end` are not mutually exclusive.** In grpc-web-text mode
 *    (which this client uses) a mid-flight non-OK status arrives as a trailer
 *    frame in the response *body*: the `readystatechange` handler emits
 *    `error`, then the `complete` handler finds no `grpc-status` among the HTTP
 *    headers and emits `end` too. The `settled` latch collapses that pair into
 *    a single reconnect.
 *
 * Disposal is reliable because the current stream is tracked in a mutable
 * binding rather than captured once: after a reconnect, `dispose()` still
 * cancels the stream that is actually open. `cancel()` itself emits neither
 * `error` nor `end` (grpc-web suppresses both for a cancelled stream), so
 * disposing cannot re-enter the reconnect path.
 *
 * @param open Opens a new stream. Called once up front and again on each retry.
 * @param onData Receives every message from whichever stream is current.
 * @param onTerminated Called once per termination, before the retry is queued.
 */
export function resilientStream<RESP>(
  open: () => ClientReadableStream<RESP>,
  onData: (response: RESP) => void,
  onTerminated?: () => void,
): ResilientStream {
  let stream: ClientReadableStream<RESP> | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  function connect(): void {
    if (disposed) return;

    let settled = false;
    const terminated = () => {
      if (disposed || settled) return;
      settled = true;
      onTerminated?.();
      retryTimer = setTimeout(connect, RETRY_DELAY_MS);
    };

    stream = open();
    stream.on("data", onData);
    stream.on("error", terminated);
    stream.on("end", terminated);
  }

  connect();

  return {
    dispose(): void {
      disposed = true;
      if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
      stream?.cancel();
      stream = null;
    },
  };
}
