import type { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import {
  reportAudioSample,
  startListening,
  stopListening,
} from "./action-dispatcher";

const TARGET_SAMPLE_RATE = 16000;
const CHUNK_DURATION_MS = 20;
const SAMPLES_PER_CHUNK = (TARGET_SAMPLE_RATE * CHUNK_DURATION_MS) / 1000; // 320

let mediaStream: MediaStream | null = null;
let audioContext: AudioContext | null = null;
let workletNode: AudioWorkletNode | null = null;

const WORKLET_PROCESSOR = `
class ChunkProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(0);
    this._samplesPerChunk = ${SAMPLES_PER_CHUNK};
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
  stopListening(store);

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

}

export function isBrowserMicActive(): boolean {
  return mediaStream !== null;
}
