#include "input.h"

#include "board.h"
#include "client_app.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_system.h"
#include "net.h"
#include "ubo_lvgl.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ubo_input";

#define BOOT_GPIO 9       /* ESP32-C6 BOOT button (active low) */
#define TOUCH_INT_GPIO 15 /* FT3168 INT: low while a touch is present */
#define POLL_MS 20        /* ~50 Hz */
#define TAP_MAX_MOVE 25 /* px: below this a press/release is a tap */
#define SWIPE_MIN 50    /* px: minimum travel for a swipe */
#define BOOT_RESET_MS 3000 /* hold BOOT this long -> clear WiFi creds + reboot */

/* Gestures -> Ubo keys:
 *   tap        -> L1/L2/L3 by which vertical third was tapped (the slot)
 *   swipe up   -> UP        swipe down -> DOWN
 *   swipe horiz-> BACK
 *   BOOT tap   -> HOME       BOOT hold (>=3s) -> clear WiFi creds + reboot to setup
 */
static void input_task(void *arg) {
    esp_lcd_touch_handle_t tp = (esp_lcd_touch_handle_t)arg;

    const gpio_config_t boot = {
        .pin_bit_mask = 1ULL << BOOT_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&boot);

    bool down = false;
    bool vol_mode = false; /* this touch started on the volume bar */
    int sx = 0, sy = 0, cx = 0, cy = 0;
    bool boot_pressed_prev = false;
    int boot_held_ms = 0;
    bool boot_reset_fired = false;

    while (1) {
        uint16_t tx[1], ty[1];
        uint8_t cnt = 0;
        esp_lcd_touch_read_data(tp);
        bool pressed = esp_lcd_touch_get_coordinates(tp, tx, ty, NULL, &cnt, 1);
        if (pressed && cnt > 0) {
            cx = tx[0];
            cy = ty[0];
            if (!down) {
                down = true;
                sx = cx;
                sy = cy;
                /* Touch on the volume bar => slide/tap-to-level control. */
                const int v = ubo_lvgl_hit_volume(cx, cy);
                vol_mode = v >= 0;
                if (vol_mode) {
                    ubo_client_set_volume(v);
                }
            } else if (vol_mode) {
                /* Keep updating volume as the finger slides up/down. */
                const int v = ubo_lvgl_hit_volume(cx, cy);
                if (v >= 0) {
                    ubo_client_set_volume(v);
                }
            }
        } else if (down) {
            down = false;
            if (vol_mode) {
                vol_mode = false; /* volume already applied during the slide */
            } else {
                const int dx = cx - sx, dy = cy - sy;
                const int adx = dx < 0 ? -dx : dx, ady = dy < 0 ? -dy : dy;
                const char *k = NULL;
                if (adx < TAP_MAX_MOVE && ady < TAP_MAX_MOVE) {
                    /* Only select if the tap landed on an actual item bar. */
                    const int slot = ubo_lvgl_hit_test(sx, sy);
                    if (slot == 0) {
                        k = "L1";
                    } else if (slot == 1) {
                        k = "L2";
                    } else if (slot == 2) {
                        k = "L3";
                    }
                } else if (ady > adx && ady > SWIPE_MIN) {
                    k = dy < 0 ? "UP" : "DOWN";
                } else if (adx > ady && adx > SWIPE_MIN) {
                    k = "BACK";
                }
                if (k) {
                    ubo_client_enqueue_key(k);
                }
            }
        }

        /* BOOT: short tap -> HOME (on release); hold >=3s -> clear WiFi creds
         * and reboot so the device comes back up in the setup portal. */
        const bool boot_pressed = gpio_get_level(BOOT_GPIO) == 0;
        if (boot_pressed) {
            boot_held_ms += POLL_MS;
            if (!boot_reset_fired && boot_held_ms >= BOOT_RESET_MS) {
                boot_reset_fired = true;
                ESP_LOGW(TAG, "BOOT held: clearing WiFi creds, rebooting to setup");
                ubo_net_creds_clear();
                esp_restart();
            }
        } else {
            if (boot_pressed_prev && !boot_reset_fired) {
                ubo_client_enqueue_key("HOME");
            }
            boot_held_ms = 0;
            boot_reset_fired = false;
        }
        boot_pressed_prev = boot_pressed;

        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}

void ubo_input_start(esp_lcd_touch_handle_t touch) {
    xTaskCreate(input_task, "ubo_input", 4096, touch, 5, NULL);
    ESP_LOGI(TAG, "touch + BOOT input started");
}
