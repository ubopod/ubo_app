import {
  reportAudioSample,
  startListening,
  stopListening,
} from "./action-dispatcher";
import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";

const TARGET_SAMPLE_RATE = 16000;
// Wall-clock audio per chunk. Each chunk becomes one unary DispatchAction, so a
// small value floods the browser's connection budget (→ ERR_INSUFFICIENT_RESOURCES).
// 100ms keeps it to ~10 dispatches/sec; streaming STT handles 100ms frames fine.
const CHUNK_DURATION_MS = 100;

let mediaStream: MediaStream | null = null;
let audioContext: AudioContext | null = null;
let workletNode: AudioWorkletNode | null = null;

const WORKLET_PROCESSOR = `
class ChunkProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(0);
    // Chunk by the context's NATIVE rate so each message is CHUNK_DURATION_MS of
    // wall-clock audio. ('sampleRate' is a global in AudioWorkletGlobalScope =
    // the native rate; the buffer holds native-rate samples.)
    this._samplesPerChunk = Math.round((sampleRate * ${CHUNK_DURATION_MS}) / 1000);
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) return true;

    const channelData = input[0];

    // Append to buffer
    const newBuffer = new Float32Array(this._buffer.length + channelData.length);
    newBuffer.set(this._buffer, 0);
    newBuffer.set(channelData, this._buffer.length);
    this._buffer = newBuffer;

    // Emit complete chunks
    while (this._buffer.length >= this._samplesPerChunk) {
      const chunk = this._buffer.slice(0, this._samplesPerChunk);
      this._buffer = this._buffer.slice(this._samplesPerChunk);
      this.port.postMessage({ chunk });
    }

    return true;
  }
}

registerProcessor('chunk-processor', ChunkProcessor);
`;

function float32ToInt16(float32: Float32Array): Uint8Array {
  const int16 = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return new Uint8Array(int16.buffer);
}

function resample(
  input: Float32Array,
  inputRate: number,
  outputRate: number,
): Float32Array {
  if (inputRate === outputRate) return input;
  const ratio = inputRate / outputRate;
  const outputLength = Math.round(input.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i++) {
    const srcIndex = i * ratio;
    const low = Math.floor(srcIndex);
    const high = Math.min(low + 1, input.length - 1);
    const frac = srcIndex - low;
    output[i] = input[low] * (1 - frac) + input[high] * frac;
  }
  return output;
}

export async function startBrowserMic(
  store: StoreServiceClient,
): Promise<void> {
  if (mediaStream) return;

  // getUserMedia only exists in a secure context. Over plain HTTP on a LAN
  // address navigator.mediaDevices is undefined, so guard with a clear message
  // instead of throwing an opaque "Cannot read properties of undefined".
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error(
      "Microphone needs a secure context. Open the web UI over HTTPS or via " +
        "localhost (or whitelist this origin in the browser's insecure-origin " +
        "flag).",
    );
  }

  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
    },
  });

  audioContext = new AudioContext();
  const nativeRate = audioContext.sampleRate;

  const blob = new Blob([WORKLET_PROCESSOR], { type: "application/javascript" });
  const workletUrl = URL.createObjectURL(blob);
  await audioContext.audioWorklet.addModule(workletUrl);
  URL.revokeObjectURL(workletUrl);

  const source = audioContext.createMediaStreamSource(mediaStream);
  workletNode = new AudioWorkletNode(audioContext, "chunk-processor");

  workletNode.port.onmessage = (e: MessageEvent<{ chunk: Float32Array }>) => {
    const resampled =
      nativeRate !== TARGET_SAMPLE_RATE
        ? resample(e.data.chunk, nativeRate, TARGET_SAMPLE_RATE)
        : e.data.chunk;
    const pcm16 = float32ToInt16(resampled);
    reportAudioSample(store, pcm16, Date.now() / 1000);
  };

  source.connect(workletNode);
  workletNode.connect(audioContext.destination); // required for processing

  startListening(store);
}

export function stopBrowserMic(store: StoreServiceClient): void {
  // Stop producing samples first so nothing is queued after the stop dispatch
  // (below) aborts the buffered audio RPCs.
  if (workletNode) {
    workletNode.disconnect();
    workletNode = null;
  }

  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }

  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }

  // Dispatch stop last: dispatch() aborts any in-flight audio-sample RPCs
  // first, so the stop isn't stuck behind them in the connection pool.
  stopListening(store);
}

export function isBrowserMicActive(): boolean {
  return mediaStream !== null;
}
