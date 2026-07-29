/**
 * @file board.h
 * Hardware bring-up seam, implemented once per supported board.
 *
 * Owns the platform peripherals (shared I2C master bus, display panel, touch
 * controller, audio codecs). The LVGL display backend
 * (src/display/backend_esp_lcd.c) wraps the panel handle; the touch input
 * driver wraps the touch handle.
 *
 * Board selection happens in main/CMakeLists.txt off IDF_TARGET (NOT off
 * CONFIG_UBO_BOARD_*: Kconfig values are undefined during ESP-IDF's early
 * requirements-expansion pass, so gating REQUIRES on them silently drops
 * components). CMake puts exactly one boards/<name>/ directory on the include
 * path, which is where board_pins.h comes from — so nothing here or in any
 * caller needs a per-board #ifdef.
 *
 * Implementations: boards/waveshare_c6_amoled/board.c, boards/esp_box_3/board.c
 */
#ifndef UBO_BOARD_H
#define UBO_BOARD_H

#include <stdbool.h>

#include "audio_codec_data_if.h"
#include "board_pins.h"
#include "driver/i2c_master.h"
#include "esp_codec_dev.h"
#include "esp_lcd_touch.h"
#include "esp_lcd_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Create the shared I2C master bus (touch + codecs + any IO-expander). */
i2c_master_bus_handle_t board_i2c_init(void);

/* Reset and initialize the display panel, and hand the resulting esp_lcd
 * handles to the renderer's esp_lcd backend via
 * ubo_backend_esp_lcd_configure() — the board is the only thing that knows the
 * panel's alignment/byte-order/buffer constraints. Must run before
 * ubo_lvgl_init(). Returns the panel handle (retained for power management). */
esp_lcd_panel_handle_t board_display_init(i2c_master_bus_handle_t i2c);

/* Initialize the capacitive touch controller on the shared I2C bus. Returns the
 * touch handle (poll with esp_lcd_touch_read_data / _get_coordinates). The
 * driver is configured to emit coordinates already in display space. */
esp_lcd_touch_handle_t board_touch_init(i2c_master_bus_handle_t i2c);

/* Enable/disable the speaker power amplifier. board_display_init() must have run
 * first on boards where the amp hangs off a display-side IO-expander. */
void board_speaker_amp_enable(bool on);

/* The board's audio codec device handles. On a board where one chip does both
 * directions (ES8311 in IN_OUT mode), `in` and `out` are the SAME handle — so
 * audio.c's split call sites collapse back to today's behaviour exactly. */
typedef struct {
    esp_codec_dev_handle_t out; /* speaker / DAC. Never NULL on success. */
    esp_codec_dev_handle_t in;  /* mic / ADC. May alias `out`. */
    float mic_gain_db;          /* board-tuned analog capture gain */
} board_codecs_t;

/* Bring up the board's codec chip(s) on the shared I2C bus, bound to `data_if`
 * (the full-duplex I2S data interface audio.c owns). Both handles share one
 * data_if — that is the topology esp_codec_dev expects, and it is what keeps
 * the TX clock reconfiguration working when only the RX side is opened.
 * Returns 0 on success. */
int board_audio_codecs_init(i2c_master_bus_handle_t i2c,
                            const audio_codec_data_if_t *data_if,
                            board_codecs_t *out);

#ifdef __cplusplus
}
#endif
#endif /* UBO_BOARD_H */
