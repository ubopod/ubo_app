import {
  SubscribeEventRequest,
  SubscribeEventResponse,
} from "../bindings/store/v1/store_pb";
import { StoreServiceClient } from "../bindings/store/v1/StoreServiceClientPb";
import {
  AudioPlayAudioSampleEvent,
  AudioPlayAudioSequenceEvent,
  AudioSample,
  AudioStopPlaybackEvent,
  Event,
} from "../bindings/ubo/v1/ubo_pb";

const audioContext = new AudioContext();

// Track all active audio sources so they can be stopped
const activeSources = new Set<AudioBufferSourceNode>();
// Generation counter to cancel in-flight async decodes after stop
let audioGeneration = 0;

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
  const gen = audioGeneration;
  return new Promise(async (resolve, reject) => {
    try {
      const data = sample.getData_asU8();
      const rate = sample.getRate();
      const width = sample.getWidth();
      const channels = sample.getChannels();

      const audioBlob = createWavFile(data, rate, channels, width * 8);
      const arrayBuffer = await audioBlob.arrayBuffer();
      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

      if (gen !== audioGeneration) { resolve(); return; }

      const source = audioContext.createBufferSource();
      source.buffer = audioBuffer;

      const gainNode = audioContext.createGain();
      gainNode.gain.value = volume;

      source.connect(gainNode);
      gainNode.connect(audioContext.destination);

      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }

      activeSources.add(source);
      source.onended = () => {
        activeSources.delete(source);
        resolve();
      };
      source.start(audioContext.currentTime + 0.1);
    } catch (err) {
      reject(err);
    }
  });
}

// Schedule a sequence chunk at a precise time to avoid gaps between chunks.
// Returns a promise that resolves when the chunk finishes, and the scheduled
// end time so the next chunk can be scheduled seamlessly.
function scheduleAudioChunk(
  sample: AudioSample,
  volume: number,
  startTime: number,
): { endTime: number; done: Promise<void> } {
  const gen = audioGeneration;
  const data = sample.getData_asU8();
  const rate = sample.getRate();
  const width = sample.getWidth();
  const channels = sample.getChannels();

  const duration = data.length / (rate * channels * (width));

  const done = new Promise<void>(async (resolve, reject) => {
    try {
      const audioBlob = createWavFile(data, rate, channels, width * 8);
      const arrayBuffer = await audioBlob.arrayBuffer();
      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

      if (gen !== audioGeneration) { resolve(); return; }

      const source = audioContext.createBufferSource();
      source.buffer = audioBuffer;

      const gainNode = audioContext.createGain();
      gainNode.gain.value = volume;

      source.connect(gainNode);
      gainNode.connect(audioContext.destination);

      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }

      activeSources.add(source);
      source.onended = () => {
        activeSources.delete(source);
        resolve();
      };
      source.start(startTime);
    } catch (err) {
      reject(err);
    }
  });

  return { endTime: startTime + duration, done };
}

// Sequence playback: buffer chunks by id, play in index order.
// Pre-schedules all available chunks using precise Web Audio API timing
// so there are no gaps between chunks.
const sequenceState = new Map<
  string,
  {
    nextIndex: number;
    buffer: Map<number, { sample: AudioSample; volume: number }>;
    nextStartTime: number;
    scheduling: boolean;
  }
>();

function flushSequenceBuffer(id: string): void {
  const seq = sequenceState.get(id);
  if (!seq || seq.scheduling) return;

  seq.scheduling = true;
  try {
    while (seq.buffer.has(seq.nextIndex)) {
      const chunk = seq.buffer.get(seq.nextIndex)!;
      seq.buffer.delete(seq.nextIndex);
      seq.nextIndex++;

      // If we've fallen behind, jump to now + small offset
      if (seq.nextStartTime < audioContext.currentTime) {
        seq.nextStartTime = audioContext.currentTime + 0.05;
      }

      const { endTime } = scheduleAudioChunk(
        chunk.sample,
        chunk.volume,
        seq.nextStartTime,
      );
      seq.nextStartTime = endTime;
    }
  } finally {
    seq.scheduling = false;
  }
}

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
      nextStartTime: audioContext.currentTime + 0.1,
      scheduling: false,
    });
  }
  const seq = sequenceState.get(id)!;
  seq.buffer.set(index, { sample, volume });

  flushSequenceBuffer(id);
}

export function subscribeToEvents(
  store: StoreServiceClient,
  setupEvents: Array<(event: Event) => void>,
  handleResponse: (response: SubscribeEventResponse) => void,
): () => void {
  const request = new SubscribeEventRequest();
  for (const setup of setupEvents) {
    const event = new Event();
    setup(event);
    request.addEvents(event);
  }

  const stream = store.subscribeEvent(request);
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let cancelled = false;

  stream.on("error", () => {
    if (!cancelled) {
      reconnectTimer = setTimeout(
        () => subscribeToEvents(store, setupEvents, handleResponse),
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

export function stopAllAudio(): void {
  audioGeneration++;
  for (const source of activeSources) {
    try {
      source.stop();
    } catch {
      // Already stopped
    }
  }
  activeSources.clear();
  sequenceState.clear();
}

export function subscribeToAudioEvents(
  store: StoreServiceClient,
): () => void {
  return subscribeToEvents(
    store,
    [
      (event) =>
        event.setAudioPlayAudioSampleEvent(new AudioPlayAudioSampleEvent()),
      (event) =>
        event.setAudioPlayAudioSequenceEvent(
          new AudioPlayAudioSequenceEvent(),
        ),
      (event) =>
        event.setAudioStopPlaybackEvent(new AudioStopPlaybackEvent()),
    ],
    (response: SubscribeEventResponse) => {
      const evt = response.getEvent();
      if (!evt) return;

      const sampleEvent = evt.getAudioPlayAudioSampleEvent();
      if (sampleEvent) {
        const audioSample = sampleEvent.getSample();
        if (audioSample) {
          playAudioSample(audioSample, sampleEvent.getVolume());
        }
        return;
      }

      const sequenceEvent = evt.getAudioPlayAudioSequenceEvent();
      if (sequenceEvent) {
        const audioSample = sequenceEvent.getSample();
        if (audioSample) {
          playSequenceChunk(
            sequenceEvent.getId(),
            sequenceEvent.getIndex(),
            audioSample,
            sequenceEvent.getVolume(),
          );
        }
        return;
      }

      if (evt.getAudioStopPlaybackEvent()) {
        stopAllAudio();
      }
    },
  );
}
