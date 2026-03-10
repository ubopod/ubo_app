import {
  SubscribeEventRequest,
  SubscribeEventResponse,
} from "../bindings/store/v1/store_pb";
import { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import {
  AudioPlayAudioSampleEvent,
  AudioPlayAudioSequenceEvent,
  AudioSample,
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

// Sequence playback: buffer chunks by id, play in index order
// Each sequence has its own playback chain to ensure serial playback.
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

  // Chain playback of all consecutive ready chunks onto the existing chain
  seq.playChain = seq.playChain.then(async () => {
    while (seq.buffer.has(seq.nextIndex)) {
      const chunk = seq.buffer.get(seq.nextIndex)!;
      seq.buffer.delete(seq.nextIndex);
      seq.nextIndex++;
      await playAudioSample(chunk.sample, chunk.volume);
    }

    // Clean up completed sequences
    if (seq.buffer.size === 0) {
      sequenceState.delete(id);
    }
  });
}

function subscribeToEvent(
  store: StoreServiceClient,
  setupEvent: (event: Event) => void,
  handleResponse: (response: SubscribeEventResponse) => void,
): () => void {
  const event = new Event();
  setupEvent(event);

  const request = new SubscribeEventRequest();
  request.setEvent(event);

  const stream = store.subscribeEvent(request);
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let cancelled = false;

  stream.on("error", () => {
    if (!cancelled) {
      reconnectTimer = setTimeout(
        () => subscribeToEvent(store, setupEvent, handleResponse),
        1000,
      );
    }
  });

  stream.on("data", handleResponse);

  return () => {
    cancelled = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    stream.cancel();
  };
}

export function subscribeToAudioEvents(
  store: StoreServiceClient,
): () => void {
  const unsubSample = subscribeToEvent(
    store,
    (event) =>
      event.setAudioPlayAudioSampleEvent(new AudioPlayAudioSampleEvent()),
    (response: SubscribeEventResponse) => {
      const audioEvent = response.getEvent()?.getAudioPlayAudioSampleEvent();
      if (!audioEvent) return;

      const audioSample = audioEvent.getSample();
      if (!audioSample) return;

      playAudioSample(audioSample, audioEvent.getVolume());
    },
  );

  const unsubSequence = subscribeToEvent(
    store,
    (event) =>
      event.setAudioPlayAudioSequenceEvent(
        new AudioPlayAudioSequenceEvent(),
      ),
    (response: SubscribeEventResponse) => {
      const audioEvent = response
        .getEvent()
        ?.getAudioPlayAudioSequenceEvent();
      if (!audioEvent) return;

      const audioSample = audioEvent.getSample();
      if (!audioSample) return;

      playSequenceChunk(
        audioEvent.getId(),
        audioEvent.getIndex(),
        audioSample,
        audioEvent.getVolume(),
      );
    },
  );

  return () => {
    unsubSample();
    unsubSequence();
  };
}
