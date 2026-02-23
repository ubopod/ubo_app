import {
  SubscribeEventRequest,
  SubscribeEventResponse,
} from "../bindings/store/v1/store_pb";
import { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import {
  AudioPlayAudioSampleEvent,
  Event,
} from "../bindings/ubo/v1/ubo_pb";

const audioContext = new AudioContext();

function createWavFile(
  samples: Uint8Array,
  sampleRate: number,
  numChannels: number,
  bitsPerSample: number,
): Blob {
  const header = new ArrayBuffer(44);
  const view = new DataView(header);

  const blockAlign = (numChannels * bitsPerSample) / 8;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length;

  function writeString(view: DataView, offset: number, str: string) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);

  const wavBuffer = new Uint8Array(header.byteLength + samples.length);
  wavBuffer.set(new Uint8Array(header), 0);
  wavBuffer.set(samples, header.byteLength);

  return new Blob([wavBuffer], { type: "audio/wav" });
}

export function subscribeToAudioEvents(store: StoreServiceClient): void {
  const event = new Event();
  event.setAudioPlayAudioSampleEvent(new AudioPlayAudioSampleEvent());

  const request = new SubscribeEventRequest();
  request.setEvent(event);

  const stream = store.subscribeEvent(request);

  stream.on("error", () =>
    setTimeout(() => subscribeToAudioEvents(store), 1000),
  );

  stream.on("data", async (response: SubscribeEventResponse) => {
    const audioEvent = response.getEvent()?.getAudioPlayAudioSampleEvent();
    if (!audioEvent) return;

    const audioSample = audioEvent.setSample().getSample();
    if (!audioSample) return;

    const data = audioSample.getData_asU8();
    const rate = audioSample.getRate();
    const width = audioSample.getWidth();
    const channels = audioSample.getChannels();
    const volume = audioEvent.getVolume();

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

    source.start(audioContext.currentTime + 0.1);
  });
}
