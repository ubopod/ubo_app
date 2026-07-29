/**
 * @file board_pins.h
 * Espressif ESP32-S3-BOX-3 board constants.
 *
 * Exactly one board directory is put on the include path by main/CMakeLists.txt
 * (selected from IDF_TARGET), so board.h and its callers include "board_pins.h"
 * unconditionally — there is no per-board #ifdef anywhere else in the tree.
 *
 * ESP32-S3-WROOM-1: dual-core Xtensa @240MHz, 512KB SRAM + 16MB octal PSRAM,
 * 16MB quad flash. Pin map cross-checked against espressif/esp-bsp
 * `bsp/esp-box-3`.
 */
#ifndef UBO_BOARD_PINS_H
#define UBO_BOARD_PINS_H

#define BOARD_NAME "ESP32-S3-BOX-3"

/* ── Display: 320x240 landscape LCD over 1-bit SPI3, driven by the
 * esp_lcd_ili9341 component. The die is natively landscape (ILI9342C-class),
 * which is why no swap_xy is needed to get 320 across — see board.c. ── */
#define BOARD_LCD_H_RES 320
#define BOARD_LCD_V_RES 240
/* Partial LVGL draw buffer height = V_RES / this, double-buffered:
 * 320*60*2 = 38,400 B each, ~77KB total out of internal DMA-capable SRAM.
 * Deliberately NOT in PSRAM — see the buf_caps note in backend_esp_lcd.h. */
#define BOARD_LCD_BUF_DIVISOR 4
/* No flush-window alignment constraint on this panel (unlike the SH8601). */
#define BOARD_LCD_ALIGN_PX 1

/* ── Buttons ── */
#define BOARD_BOOT_GPIO 0 /* BOOT / "config", active low */
/* Mute: GPIO1 is driven by logic gates and reports mute *state*; input.c acts
 * on the transition into the asserted level, not on the level itself. */
#define BOARD_MUTE_GPIO 1

/* ── Touch: GT911 on the shared I2C bus. The BSP applies no touch mirroring for
 * GT911 (only for the TT21100 on the older ESP-BOX), even though the panel is
 * mirrored — the touch glass is mounted to match. Verify on first light. ── */
#define BOARD_TOUCH_SWAP_XY 0
#define BOARD_TOUCH_MIRROR_X 0
#define BOARD_TOUCH_MIRROR_Y 0

/* ── Gesture thresholds (px), scaled from the C6's 448px-tall reference ── */
#define BOARD_TAP_MAX_MOVE 14 /* below this a press/release is a tap */
#define BOARD_SWIPE_MIN 28    /* minimum travel for a swipe */

/* ── Audio: ES8311 DAC (speaker) + ES7210 ADC (two mics) sharing one I2S bus ── */
#define BOARD_I2S_MCLK_GPIO 2
#define BOARD_I2S_BCLK_GPIO 17
#define BOARD_I2S_WS_GPIO 45
#define BOARD_I2S_DOUT_GPIO 15 /* I2S -> ES8311 DAC -> speaker */
#define BOARD_I2S_DIN_GPIO 16  /* ES7210 ADC (mics) -> I2S */
#define BOARD_MIC_GAIN_DB 30.0f

/* ── Infrared (PHASE 2, and only present on the ESP32-S3-BOX-3-SENSOR dock,
 * routed through the PCIe connector — NOT on the main unit) ──
 *   TX   = GPIO39
 *   RX   = GPIO38
 *   CTRL = GPIO44  <-- this is UART0 RX by default. Claiming it for IR means
 *                      moving or dropping the UART console. Do not wire this
 *                      up without dealing with that first. */

#endif /* UBO_BOARD_PINS_H */
