import { inflate } from "fflate";

import {
  DispatchActionRequest,
  SubscribeEventRequest,
  SubscribeEventResponse,
} from "../bindings/store/v1/store_pb";
import { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import {
  Action,
  AudioPlayAudioSampleEvent,
  AudioPlayAudioSequenceEvent,
  AudioSample,
  DisplayCompressedRenderEvent,
  Event,
  DisplayRedrawAction,
} from "../bindings/ubo/v1/ubo_pb";

function requestRedraw(store: StoreServiceClient) {
  const dispatchActionRequest = new DispatchActionRequest();

  const action = new Action();
  dispatchActionRequest.setAction(action);

  const displayRedrawAction = new DisplayRedrawAction();
  action.setDisplayRedrawAction(displayRedrawAction);

  store.dispatchAction(dispatchActionRequest);
}

function subscribeToRenderEvents(
  store: StoreServiceClient,
  canvas: HTMLCanvasElement | null,
) {
  const event = new Event();
  event.setDisplayCompressedRenderEvent(new DisplayCompressedRenderEvent());

  const subscribeEventRequest = new SubscribeEventRequest();
  subscribeEventRequest.setEvent(event);

  const stream = store.subscribeEvent(subscribeEventRequest);

  let context = canvas?.getContext("2d");

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
    if (width !== canvas.width || height !== canvas.height) {
      canvas.width = width;
      canvas.height = height;
      context = canvas.getContext("2d");
    }
    inflate(compressedData, (error, data) => {
      if (error) {
        console.error(error);
        return;
      }
      if (context && data) {
        const [y1, x1, y2, x2] = rectangle;
        const [width, height] = [x2 - x1, y2 - y1];

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

  requestRedraw(store);
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

function playAudioSample(
  sample: AudioSample,
  volume: number,
): Promise<void> {
  return new Promise(async (resolve, reject) => {
    try {
      const data = sample.getData_asU8();
      const rate = sample.getRate();
      const width = sample.getWidth();
      const channels = sample.getChannels();

      const audioBlob = createWavFile(data, rate, channels, width * 8);
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

      source.onended = () => resolve();
      source.start(audioContext.currentTime + 0.1);
    } catch (err) {
      reject(err);
    }
  });
}

const sequenceState = new Map<
  string,
  {
    nextIndex: number;
    buffer: Map<number, { sample: AudioSample; volume: number }>;
    playChain: Promise<void>;
  }
>();

function playSequenceChunk(
  id: string,
  index: number,
  sample: AudioSample,
  volume: number,
): void {
  if (!sequenceState.has(id)) {
    sequenceState.set(id, {
      nextIndex: 0,
      buffer: new Map(),
      playChain: Promise.resolve(),
    });
  }
  const seq = sequenceState.get(id)!;
  seq.buffer.set(index, { sample, volume });

  seq.playChain = seq.playChain.then(async () => {
    while (seq.buffer.has(seq.nextIndex)) {
      const chunk = seq.buffer.get(seq.nextIndex)!;
      seq.buffer.delete(seq.nextIndex);
      seq.nextIndex++;
      await playAudioSample(chunk.sample, chunk.volume);
    }

    if (seq.buffer.size === 0) {
      sequenceState.delete(id);
    }
  });
}

function subscribeToAudioSampleEvents(store: StoreServiceClient) {
  const event = new Event();
  event.setAudioPlayAudioSampleEvent(new AudioPlayAudioSampleEvent());

  const subscribeEventRequest = new SubscribeEventRequest();
  subscribeEventRequest.setEvent(event);

  const stream = store.subscribeEvent(subscribeEventRequest);

  stream.on("error", () =>
    setTimeout(() => subscribeToAudioSampleEvents(store), 1000),
  );
  stream.on("data", async (response: SubscribeEventResponse) => {
    const audioEvent = response.getEvent()?.getAudioPlayAudioSampleEvent();
    if (!audioEvent) return;

    const audioSample = audioEvent.getSample();
    if (!audioSample) return;

    playAudioSample(audioSample, audioEvent.getVolume());
  });
}

function subscribeToAudioSequenceEvents(store: StoreServiceClient) {
  const event = new Event();
  event.setAudioPlayAudioSequenceEvent(new AudioPlayAudioSequenceEvent());

  const subscribeEventRequest = new SubscribeEventRequest();
  subscribeEventRequest.setEvent(event);

  const stream = store.subscribeEvent(subscribeEventRequest);

  stream.on("error", () =>
    setTimeout(() => subscribeToAudioSequenceEvents(store), 1000),
  );
  stream.on("data", async (response: SubscribeEventResponse) => {
    const audioEvent = response.getEvent()?.getAudioPlayAudioSequenceEvent();
    if (!audioEvent) return;

    const audioSample = audioEvent.getSample();
    if (!audioSample) return;

    playSequenceChunk(
      audioEvent.getId(),
      audioEvent.getIndex(),
      audioSample,
      audioEvent.getVolume(),
    );
  });
}

export function subscribeToStoreEvents(
  store: StoreServiceClient,
  canvas: HTMLCanvasElement | null,
) {
  subscribeToRenderEvents(store, canvas);
  subscribeToAudioSampleEvents(store);
  subscribeToAudioSequenceEvents(store);
}
