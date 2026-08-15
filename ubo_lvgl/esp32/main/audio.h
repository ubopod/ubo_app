/**
 * @file audio.h
 * Speaker playback + microphone capture for the board's onboard codec (ES8311
 * on the C6; ES8311 DAC + ES7210 mic ADC on the S3-BOX-3). Codec control lives
 * on the shared I2C bus; a single full-duplex I2S channel pair carries PCM.
 *
 * Playback and capture are mutually exclusive, and not by choice: they share
 * one I2S port and therefore one bit clock, and esp_codec_dev refuses to open
 * the paired device at a different sample rate. So one esp_codec_dev handle is
 * open at a time and the two take turns.
 *
 * With CONFIG_UBO_WAKE_ENABLE the microphone is additionally held open whenever
 * the speaker is idle, so esp-sr's WakeNet can listen for the wake word — see
 * ubo_audio_wake_bind(). Playback then takes the codec back from the wake
 * listener rather than being refused, and there is no barge-in: the device is
 * deaf while it talks.
 *
 * ESP32-only: nothing here is compiled into the desktop/Pi renderer.
 */
#ifndef UBO_AUDIO_H
#define UBO_AUDIO_H

#include <stdbool.h>
#include <stddef.h> /* size_t */
#include <stdint.h>

#include "driver/i2c_master.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Bring up the ES8311 codec (on the shared I2C bus) + full-duplex I2S + PA.
 * Returns 0 on success. Logs free heap before/after. */
int ubo_audio_init(i2c_master_bus_handle_t i2c);

/* Speaker: queue `len` bytes of raw PCM for playback at (rate, channels, width)
 * where width is BYTES per sample (16-bit => 2). `volume` is 0..1. Non-blocking
 * (bounded ring; brief block if full). Dropped while a talk session is
 * streaming; merely listening for the wake word yields the codec instead. */
void ubo_audio_play(const uint8_t *pcm, size_t len, int rate, int channels,
                    int width, float volume);

/* Stop playback: discard everything queued in the play ring (core dispatched
 * AudioStopPlaybackEvent, e.g. video stopped). Async; applied by the play task
 * within one ~50ms drain cycle. */
void ubo_audio_stop_playback(void);

/* Mic / PTT: switch to 16 kHz mono capture and start streaming. The capture
 * task invokes `cb` with each chunk (CONFIG_UBO_MIC_CHUNK_MS of 16-bit PCM).
 * `timestamp` is seconds. ubo_audio_mic_stop() ends the session. */
typedef void (*ubo_audio_mic_cb)(void *user, const uint8_t *pcm, size_t len,
                                 float timestamp);
void ubo_audio_mic_start(ubo_audio_mic_cb cb, void *user);
void ubo_audio_mic_stop(void);

/* Wake word (CONFIG_UBO_WAKE_ENABLE; a no-op otherwise). Registers `cb`, called
 * from the capture task the moment WakeNet matches, with the phrase the loaded
 * model listens for ("Jarvis"). `mic_cb`/`mic_user` are the callbacks a session
 * started this way will stream through, registered here rather than at wake
 * time so no audio is delivered to a NULL callback in between.
 *
 * By the time `cb` runs, capture has ALREADY been promoted to a streaming
 * session — the audio is buffering, and `cb` only has to tell the core. It must
 * not block: it runs on the capture task. */
typedef void (*ubo_audio_wake_cb)(void *user, const char *phrase);
void ubo_audio_wake_bind(ubo_audio_wake_cb cb, void *user,
                         ubo_audio_mic_cb mic_cb, void *mic_user);

/* Hardware mute. While muted the microphone is CLOSED, not merely ignored —
 * an always-on wake word that kept capturing through a mute switch would be
 * exactly the thing the switch exists to prevent. Idempotent; safe to call
 * every poll. Unmuting re-arms listening within one playback cycle (~50ms). */
void ubo_audio_wake_set_muted(bool muted);

#ifdef __cplusplus
}
#endif
#endif /* UBO_AUDIO_H */
