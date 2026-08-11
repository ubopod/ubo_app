import type { Cancelable, StreamSink } from "./fetch-stream";

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
 * **Every termination means "reconnect".** A graceful server shutdown ends the
 * stream with an OK status, which is indistinguishable from a crash as far as
 * the page is concerned — treating only failures as reconnect-worthy would
 * leave the UI permanently blank after a restart. {@link StreamSink.onEnd}
 * fires once either way, and stays silent for a deliberate `cancel()`, so
 * disposal cannot re-enter the reconnect path.
 *
 * Disposal is reliable because the current stream is tracked in a mutable
 * binding rather than captured once: after a reconnect, `dispose()` still
 * cancels the stream that is actually open.
 *
 * @param open Opens a new stream. Called once up front and again on each retry.
 * @param onData Receives every message from whichever stream is current.
 * @param onTerminated Called once per termination, before the retry is queued.
 */
export function resilientStream<RESP>(
  open: (sink: StreamSink<RESP>) => Cancelable,
  onData: (response: RESP) => void,
  onTerminated?: (error?: Error) => void,
): ResilientStream {
  let stream: Cancelable | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  function connect(): void {
    if (disposed) return;

    stream = open({
      onData,
      onEnd: (error) => {
        if (disposed) return;
        onTerminated?.(error);
        retryTimer = setTimeout(connect, RETRY_DELAY_MS);
      },
    });
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
