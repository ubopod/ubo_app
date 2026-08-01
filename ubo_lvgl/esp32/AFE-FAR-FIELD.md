# Far-field AFE on the ESP32-S3-BOX-3 — what we tried, what we learned

Status: **not working.** The device currently runs `AFE_TYPE_VC`, which is
single-microphone with noise suppression and AGC. It measures well (word-perfect
transcription at 1.5 m) but it is *not* far-field. Dual-microphone blind source
separation — the thing that makes far-field work — has never produced usable
audio here.

This is a reference for picking the work back up, written after a long session
that ruled out a lot and found the likely root cause without landing it.

---

## The hardware, stated precisely

Espressif's own board support for this exact board — esp-skainet,
`components/hardware_driver/boards/esp32s3-box-3/bsp_board.c` — is the
authoritative source:

```c
#define ADC_I2S_CHANNEL 4                                    // FOUR TDM slots
.mic_selected = ES7120_SEL_MIC1 | MIC2 | MIC3 | MIC4;        // all four ADCs

char* bsp_get_input_format(void) { return "RMNM"; }

esp_err_t bsp_get_feed_data(...) {
    esp_codec_dev_read(record_dev, buffer, buffer_len);      // 4 channels
    for (int i = 0; i < audio_chunksize; i++) {
        int16_t ref = buffer[4 * i + 0];        // slot 0 = playback REFERENCE
        buffer[3 * i + 0] = buffer[4 * i + 1];  // slot 1 = microphone
        buffer[3 * i + 1] = buffer[4 * i + 3];  // slot 3 = microphone
        buffer[3 * i + 2] = ref;                // repacked to "MMR"
    }
}
```

**The ES7210 is a 4-slot TDM device. Slot 0 is the playback reference, not a
microphone. The two microphones are on slots 1 and 3.**

Our driver has historically opened it as **2-channel I2S STD**, which yields
slots 0 and 1 — that is, `[reference, microphone]` — while telling AFE the
format was `"MM"` (two microphones). BSS was being asked to separate two
sources from one microphone and a silent reference channel. **This is almost
certainly the root cause of every BSS failure below.**

Corroborating detail that went uninterpreted for a long time: with `"MM"` and
two channels fed, AFE reported `raw_data_channels = 3` and
`trigger_channel_id = 2` — consistent with the 3-channel `[mic, mic, ref]`
layout it expected, channel 2 being a reference we never supplied.

---

## What the esp-sr library itself enforces

AFE ships precompiled, so these came from `strings` on
`lib/esp32s3/libesp_audio_front_end.a`. They are not in the public docs and they
settle several questions:

```
"AFE_TYPE_VC only support single microphone channel. If input is
 multi-channels, the first channel will be selected"
"For single microphone channel, SE is deactivated."
"The AFE supports two microphone channels at the most. The first two
 channels will be selected."
"Only support single reference channel for AEC, but got %d, ..."
"The playback reference channel is 0, the AEC is deactivated."
"Noise Supression may reduce the accuracy of speech recognition. It is not
 recommended to turn it on."
"unknown character: %c, please use M: microphone channel, R: reference
 channel, N: unknown channel"
```

Consequences:

- **`AFE_TYPE_VC` can never do far-field.** It is single-mic by definition, and
  a single mic auto-disables SE. `afe_config_check()` silently rewrites
  `pcm_config.mic_num` 2 → 1 and `se_init` → false. Confirmed on device.
- **Far-field requires `AFE_TYPE_SR` + two microphones + `se_init`.**
- There are two separate implementations behind
  `esp_afe_handle_from_config()`: `esp_afe_sr_1mic` and `esp_afe_sr_2mic`.
- `afe_config_check()` modifies the config in place. **Always log
  `pcm_config` AFTER the check** — what you asked for is often not what you got.

---

## Configurations tried, and what each produced

All measured with `tests/hardware` (see below), satellite at 1.5 m, same
position, one variable at a time.

| # | Config | Result |
|---|---|---|
| 1 | `SR`, `se_init=false` | envelope 0.722, −20.1 dBFS. Works; no processing at all (falls back to first mic). |
| 2 | `SR`, `se_init=true`, `"MM"` | envelope **0.196**, output pinned −0.0 dBFS w/ clipping. Dead-flat level, no dynamics. STT hallucinated (`"I love you."`). |
| 3 | `VC` | envelope 0.644, −11.3 dBFS, NS+AGC running. **Best working config**; but `config_check` forced mic_num→1, se→false. Single-mic. |
| 4 | `SR`, `se_init=true`, `"MMR"` (2ch read, zero-filled reference) | envelope **0.216**. Identical failure to #2. STT hallucinated (`"Aproveito a oferta."`). |
| 5 | #4 + `agc_init=false` | Output still dead-flat. **Not an AGC artifact.** |
| 6 | #4 + `vad_init=true`, `vad_enable_channel_trigger=true`, `fixed_output_channel=false` | No change. `trigger_channel_id` stayed pinned at 2 in every variant, though VAD itself worked (vad=1 exactly during speech). |
| 7 | **4-slot TDM**, all 4 ADCs, repack slots 1/3/0 → `"MMR"` | Config finally correct: `ES7210: Enable TDM mode`, `mic=2 ref=1`, `SE(BSS)` in pipeline, capture 101% real-time. **But fetch produced nothing** — zero `report_sample` dispatches upstream. Not yet diagnosed. |

Configuration #7 is the promising one and where to resume.

### Ruled out by measurement

- **AGC** amplifying silence (#5)
- **Channel layout** as the sole issue — `"MM"` and `"MMR"` behaved identically
  while still reading only 2 slots (#2, #4)
- **Channel selection** via VAD or `fixed_output_channel` (#6)
- **Proto/binding skew** between core and subprocess — both verified identical
- **Piper / TTS / the assistant service** — 113 unit tests pass plus a real
  Piper round-trip; a long detour chasing a phantom here was caused by a broken
  probe (see Traps)

---

## Where to resume

1. **Reinstate configuration #7** (4-slot TDM). The diff is small: select all
   four ADCs in `boards/esp_box_3/board.c`, open the capture device with
   `channel = 4`, and repack slots `[1, 3, 0]` into `"MMR"` in
   `afe_feed_task`. The feed path is already general — it interleaves into
   whatever frame width AFE reports.
2. **Instrument the fetch side**, which is the unknown: log `res->ret_value`,
   `res->data_size`, `raw_data_channels` and `trigger_channel_id` per fetch.
   Previously fetch returned *garbage*; under #7 it returned *nothing*, which
   is a different failure and probably a size/geometry mismatch.
3. **Re-derive every buffer size from AFE**, not from assumptions:
   `get_feed_chunksize()`, `get_feed_channel_num()`, `get_fetch_chunksize()`.
   The codec now delivers 4 slots per frame while AFE wants 3 — the repack loop
   bounds and `afe_mic_bytes` must both come from those calls.
4. **Budget internal RAM first.** Opening 4 channels makes `esp_codec_dev`
   widen the slots to 32 bits (`set_drv_fs`: `slot_bits * fs->channel / 2` when
   `channel > 2`), doubling the I2S DMA footprint.
   `i2s_alloc_dma_desc: allocate DMA buffer failed` took the device down until
   `BOARD_LCD_BUF_DIVISOR` was raised 8 → 16 to free DMA-capable RAM.
5. **Bonus once slot 0 is wired:** it is a *real hardware playback reference*,
   so AEC becomes possible. The device currently cannot hear over its own
   speaker at all.

---

## Traps that cost real time

- **Internal RAM is the binding constraint on this board**, not PSRAM.
  `esp_get_free_heap_size()` reports ~16 MB (PSRAM) while internal DRAM is
  ~190 KB at boot and only **~3 KB once WiFi and the client have started**.
  Anything needing internal RAM — task stacks, DMA descriptors — must be
  allocated at boot or put in PSRAM. Two separate crashes came from ignoring
  this (8 KB AFE stacks killed the input task; the DMA bump above).
- **A silent `xTaskCreate` failure looks exactly like a DSP bug.** The AFE
  tasks were being created per session, failed at 3 KB free, and `fetch()` went
  on returning the ring's stale contents — presenting as "AFE always outputs
  the same constant". Create them once at boot, park them on semaphores, and
  put their stacks in PSRAM.
- **Raw waveform correlation is useless across an acoustic path.** Reverb plus
  independent 48 kHz playback and 16 kHz capture clocks drive it to ~0.01 even
  for a perfect capture. Use the 20 ms energy envelope (`tests/hardware/audio_metrics.py`).
- **Lost audio leaves a splice, not silence.** Silence-run detection cannot see
  it; `coverage_pct` and the inter-chunk gap distribution can.
- **`UboRPCClient.dispatch()` is fire-and-forget** on the client's own loop. A
  dispatch issued shortly before the client closes is silently dropped — the
  core never sees it and nothing raises. This made a perfectly healthy
  assistant look dead for hours. **Always await `stub.dispatch_action()`.**
- **Do not flash the merged image at `0x0` on a provisioned device.** It is
  `0xFF` across the NVS region (0x9000–0xF000) and erases the Wi-Fi
  credentials, dropping the board into its captive portal. Flash the app only:
  `esptool --chip esp32s3 --port <tty> write-flash 0x10000 ubo_lvgl_esp32s3.bin`.
- **`tests/setup.sh` deletes every Wi-Fi connection on a Raspberry Pi**, and
  `tests/conftest.py` runs it via an autouse fixture for *any* test. The
  hardware tests shadow that fixture; do not remove the override.
- **pppd owns the satellite's USB console** via `99-ubo-esp32-ppp.rules`, and
  resetting the board re-enumerates USB and re-triggers udev. Mask the unit for
  the duration of a run, not just stop it (`scripts/test_hil.sh` does this).
- **Do not let the test make sound of its own.** `AudioSetVolumeAction(OUTPUT)`
  emits `Chime.VOLUME_CHANGE`; that chime landing before the sentence left the
  satellite at its noise floor for a whole session and was briefly misdiagnosed
  as a device defect.

---

## Measuring any of this

`uv run poe device:test:hil` — the pod speaks a known sentence via Piper, the
satellite hears it over the air and streams it back, and the recording is
scored on two axes (signal + transcription against a reference control).
See `tests/hardware/`. Enable Settings → System → General → **Asst. Debug** and
each session is written to `~/.local/share/ubo/assistant_sessions/<ts>-<source>/`
as `mic.wav`, `reference.wav` and `session.json`.

Baseline to beat, single-mic `VC` at 1.5 m:

```
coverage 98.3%   gaps 222.9/238.2/240.1 ms   peak -7.4 dBFS   envelope 0.768
transcription ratio 1.00, keyword coverage 1.00, air-path cost -0.03
```

Far-field should beat this **at distance**, which is where it matters and where
single-mic degrades. Near-field is the condition least likely to show a
difference.

### Known-good rollback

`AFE_TYPE_VC`, `"MM"`, `se_init=false`, `ns_init=true`, `agc_init=true`,
2-channel capture, `BOARD_LCD_BUF_DIVISOR 8`. This is what is committed.

### Open issue at time of writing

After rolling back to the above, the device boots healthy and logs its VC
pipeline, Wi-Fi and client connection — but a harness run produced no session.
The core is active, `assistant_debug` is on and capture is unmuted, so this is
unexplained and needs a fresh look before trusting the next comparison.
