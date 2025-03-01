import { inflate } from "fflate";

import {
  SubscribeEventRequest,
  SubscribeEventResponse,
} from "../generated/store/v1/store_pb";
import { StoreServiceClient } from "../generated/store/v1/StoreServiceClientPb";
import {
  AudioPlayAudioEvent,
  DisplayCompressedRenderEvent,
  Event,
} from "../generated/ubo/v1/ubo_pb";

function subscribeToRenderEvents(
  store: StoreServiceClient,
  canvas: HTMLCanvasElement | null,
) {
  const event = new Event();
  event.setDisplayCompressedRenderEvent(new DisplayCompressedRenderEvent());

  const subscribeEventRequest = new SubscribeEventRequest();
  subscribeEventRequest.setEvent(event);

  const stream = store.subscribeEvent(subscribeEventRequest);

  stream.on("error", () =>
    setTimeout(() => subscribeToRenderEvents(store, canvas), 1000),
  );
  stream.on("data", (response: SubscribeEventResponse) => {
    const renderEvent = response.getEvent()?.getDisplayCompressedRenderEvent();
    if (!renderEvent || !canvas) {
      return;
    }

    const compressedData = renderEvent.getCompressedData_asU8();
    const rectangle = renderEvent.getRectangleList();
    if (!compressedData || !rectangle) {
      return;
    }
    const width = Math.round(240 * renderEvent.getDensity());
    const height = Math.round(240 * renderEvent.getDensity());
    if (width !== canvas.width) canvas.width = width;
    if (height !== canvas.height) canvas.height = height;
    inflate(compressedData, (error, data) => {
      if (error) {
        console.error(error);
        return;
      }
      if (data) {
        const [y1, x1, y2, x2] = rectangle;
        const [width, height] = [x2 - x1, y2 - y1];

        const context = canvas.getContext("2d");

        if (!context) return;

        context.putImageData(
          new ImageData(new Uint8ClampedArray(data), width, height),
          x1,
          y1,
          0,
          0,
          width,
          height,
        );
      }
    });
  });
}

export const audioContext = new AudioContext();

function createWavFile(
  samples: Uint8Array,
  sampleRate: number,
  numChannels: number,
  bitsPerSample: number,
): Blob {
  const header = new ArrayBuffer(44);
  const view = new DataView(header);

  /* Write WAV file header */
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length;

  // 'RIFF' chunk descriptor
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true); // File size minus first 8 bytes
  writeString(view, 8, "WAVE");

  // 'fmt ' sub-chunk
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true); // SubChunk1Size for PCM
  view.setUint16(20, 1, true); // AudioFormat (1 = PCM)
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);

  // 'data' sub-chunk
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);

  function writeString(view: DataView, offset: number, string: string) {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  }

  const wavBuffer = new Uint8Array(header.byteLength + samples.length);
  wavBuffer.set(new Uint8Array(header), 0);
  wavBuffer.set(samples, header.byteLength);

  return new Blob([wavBuffer], { type: "audio/wav" });
}

function subscribeToAudioEvents(store: StoreServiceClient) {
  const event = new Event();
  event.setAudioPlayAudioEvent(new AudioPlayAudioEvent());

  const subscribeEventRequest = new SubscribeEventRequest();
  subscribeEventRequest.setEvent(event);

  const stream = store.subscribeEvent(subscribeEventRequest);

  stream.on("error", () =>
    setTimeout(() => subscribeToAudioEvents(store), 1000),
  );
  stream.on("data", async (response: SubscribeEventResponse) => {
    const audioEvent = response.getEvent()?.getAudioPlayAudioEvent();

    if (!audioEvent) {
      return;
    }

    const sample = audioEvent.getSample_asU8();
    const rate = audioEvent.getRate();
    const width = audioEvent.getWidth();
    const channels = audioEvent.getChannels();
    const volume = audioEvent.getVolume();

    const audioBlob = createWavFile(sample, rate, channels, width * 8);
    const arrayBuffer = await audioBlob.arrayBuffer();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;

    const gainNode = audioContext.createGain();
    gainNode.gain.value = volume;

    source.connect(gainNode);
    gainNode.connect(audioContext.destination);

    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }

    source.start(audioContext.currentTime + 0.1);
  });
}

export function subscribeToStoreEvents(
  store: StoreServiceClient,
  canvas: HTMLCanvasElement | null,
) {
  subscribeToRenderEvents(store, canvas);
  subscribeToAudioEvents(store);
}
