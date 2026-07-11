/**
 * @file audio.h
 * Speaker playback + push-to-talk microphone capture for the ESP32-C6 board's
 * onboard ES8311 codec. The codec control lives on the shared I2C bus; a single
 * full-duplex I2S channel pair carries PCM. Playback and mic capture are mutually
 * exclusive (PTT), so one esp_codec_dev handle is opened/closed per session.
 *
 * ESP32-only: nothing here is compiled into the desktop/Pi renderer.
 */
#ifndef UBO_AUDIO_H
#define UBO_AUDIO_H

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
 * (bounded ring; brief block if full). Dropped while the mic is active. */
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

#ifdef __cplusplus
}
#endif
#endif /* UBO_AUDIO_H */
