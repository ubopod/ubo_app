/**
 * @file board_pins.h
 * Waveshare ESP32-C6-Touch-AMOLED-1.8 board constants.
 *
 * Exactly one board directory is put on the include path by main/CMakeLists.txt
 * (selected from IDF_TARGET), so board.h and its callers include "board_pins.h"
 * unconditionally — there is no per-board #ifdef anywhere else in the tree.
 *
 * ESP32-C6: single-core RISC-V, 512KB SRAM, NO PSRAM, 16MB flash.
 */
#ifndef UBO_BOARD_PINS_H
#define UBO_BOARD_PINS_H

#define BOARD_NAME "Waveshare ESP32-C6-Touch-AMOLED-1.8"

/* ── Display: SH8601 AMOLED over QSPI (SPI2) ── */
#define BOARD_LCD_H_RES 368
#define BOARD_LCD_V_RES 448
/* Partial LVGL draw buffer height = V_RES / this, double-buffered. 1/10 screen
 * keeps two 32KB buffers in the C6's DMA-capable SRAM (no PSRAM to fall back on). */
#define BOARD_LCD_BUF_DIVISOR 10
/* The SH8601 requires 2-pixel-aligned flush windows on both axes. */
#define BOARD_LCD_ALIGN_PX 2

/* ── Buttons ── */
#define BOARD_BOOT_GPIO 9  /* BOOT, active low */
#define BOARD_MUTE_GPIO -1 /* no dedicated mute button on this board */

/* ── Touch: FT3168 (esp_lcd_touch_ft5x06), coordinates already in display space ── */
#define BOARD_TOUCH_SWAP_XY 0
#define BOARD_TOUCH_MIRROR_X 0
#define BOARD_TOUCH_MIRROR_Y 0

/* ── Gesture thresholds (px) ── */
#define BOARD_TAP_MAX_MOVE 25 /* below this a press/release is a tap */
#define BOARD_SWIPE_MIN 50    /* minimum travel for a swipe */

/* ── Audio: ES8311 (single chip, both directions) over I2S0 ── */
#define BOARD_I2S_MCLK_GPIO 19
#define BOARD_I2S_BCLK_GPIO 20
#define BOARD_I2S_WS_GPIO 22
#define BOARD_I2S_DOUT_GPIO 23 /* I2S -> codec DAC -> speaker */
#define BOARD_I2S_DIN_GPIO 21  /* codec ADC (mic) -> I2S */
#define BOARD_MIC_GAIN_DB 30.0f

#endif /* UBO_BOARD_PINS_H */
