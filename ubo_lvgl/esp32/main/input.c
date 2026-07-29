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

/* Pins and gesture thresholds come from the selected board's board_pins.h (via
 * board.h). The touch INT pin is owned by board_touch_init(); the driver is
 * polled here, not interrupt-driven. */
#define BOOT_GPIO BOARD_BOOT_GPIO /* BOOT button (active low) */
#define MUTE_GPIO BOARD_MUTE_GPIO /* mute button/state line, or -1 if absent */
#define POLL_MS 20                /* ~50 Hz */
#define TAP_MAX_MOVE BOARD_TAP_MAX_MOVE /* px: below this a press/release is a tap */
#define SWIPE_MIN BOARD_SWIPE_MIN       /* px: minimum travel for a swipe */
#define RELEASE_DEBOUNCE 2 /* empty reads (≈40ms) before a touch counts as ended */
#ifndef CONFIG_UBO_TALK_HOLD_MS
#define CONFIG_UBO_TALK_HOLD_MS 350
#endif
#define TALK_HOLD_MS CONFIG_UBO_TALK_HOLD_MS /* hold BOOT this long -> push-to-talk */
#define BOOT_RESET_MS 8000 /* hold BOOT this long -> clear WiFi creds + reboot */

/* Gestures -> Ubo keys:
 *   tap        -> the transport switch, if the disconnect overlay is showing it;
 *                 otherwise L1/L2/L3 by which vertical third was tapped (the slot)
 *   swipe up   -> UP        swipe down -> DOWN
 *   swipe horiz-> BACK
 *   BOOT tap   -> HOME
 *   BOOT hold  -> push-to-talk (stream mic while held; release stops)
 *   BOOT hold (>=8s) -> clear WiFi creds + transport preference, reboot to setup
 */
static void input_task(void *arg) {
    esp_lcd_touch_handle_t tp = (esp_lcd_touch_handle_t)arg;

    const gpio_config_t boot = {
        .pin_bit_mask = 1ULL << BOOT_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&boot);

#if MUTE_GPIO >= 0
    const gpio_config_t mute = {
        .pin_bit_mask = 1ULL << MUTE_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&mute);
    /* Seed from the pin's ACTUAL level, not from false. On the BOX-3 this is a
     * logic-gate output reporting mute *state*, and it can legitimately idle
     * low — seeding false would read that as a fresh press on the first poll
     * and silently mute the microphone at every boot. */
    bool mute_pressed_prev = gpio_get_level(MUTE_GPIO) == 0;
    ESP_LOGI(TAG, "mute line (GPIO%d) idles %s", MUTE_GPIO,
             mute_pressed_prev ? "low/asserted" : "high/released");
#endif

    bool down = false;
    bool vol_mode = false; /* this touch started on the volume bar */
    int release_polls = 0; /* consecutive empty reads while a touch is active */
    int sx = 0, sy = 0, cx = 0, cy = 0;
    bool boot_pressed_prev = false;
    int boot_held_ms = 0;
    bool boot_reset_fired = false;
    bool talk_active = false; /* a push-to-talk session is streaming */

    while (1) {
        uint16_t tx[1], ty[1];
        uint8_t cnt = 0;
        esp_lcd_touch_read_data(tp);
        bool pressed = esp_lcd_touch_get_coordinates(tp, tx, ty, NULL, &cnt, 1);
        if (pressed && cnt > 0) {
            release_polls = 0;
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
        } else if (down && ++release_polls >= RELEASE_DEBOUNCE) {
            /* The FT3168 briefly reports no contact mid-drag; only end the touch
             * after RELEASE_DEBOUNCE empty reads so one fast swipe isn't split
             * into two gestures (which would skip a page). cx/cy keep their last
             * values across the dropout, so the merged swipe is classified once. */
            down = false;
            release_polls = 0;
            if (vol_mode) {
                vol_mode = false; /* volume already applied during the slide */
            } else {
                const int dx = cx - sx, dy = cy - sy;
                const int adx = dx < 0 ? -dx : dx, ady = dy < 0 ? -dy : dy;
                const char *k = NULL;
                if (adx < TAP_MAX_MOVE && ady < TAP_MAX_MOVE &&
                    ubo_lvgl_hit_transport_switch(sx, sy)) {
                    /* Only hittable while the disconnect overlay is up, so this
                     * can't shadow a menu tap. Offer the transport we are NOT on
                     * — from the active transport, not the stored preference
                     * (they differ when pref is "usb" but we booted WiFi for
                     * lack of a host). Then reboot: the client's base URL is
                     * fixed at creation, so switching link means starting over. */
                    const bool to_wifi = !ubo_net_transport_active_is_wifi();
                    ESP_LOGW(TAG, "transport switch tapped: rebooting into %s",
                             to_wifi ? "wifi" : "usb");
                    ubo_net_transport_save(to_wifi);
                    esp_restart();
                } else if (adx < TAP_MAX_MOVE && ady < TAP_MAX_MOVE) {
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

        /* BOOT button duration ladder: tap -> HOME, hold -> push-to-talk
         * (stream while held), very long hold (>=8s) -> clear WiFi creds and
         * reboot into the setup portal. Talk and reset don't collide: a normal
         * utterance is far shorter than 8s. */
        const bool boot_pressed = gpio_get_level(BOOT_GPIO) == 0;
        if (boot_pressed) {
            boot_held_ms += POLL_MS;
            if (!talk_active && !boot_reset_fired && boot_held_ms >= TALK_HOLD_MS) {
                talk_active = true;
                ubo_client_talk_start();
            }
            if (!boot_reset_fired && boot_held_ms >= BOOT_RESET_MS) {
                boot_reset_fired = true;
                if (talk_active) {
                    ubo_client_talk_stop();
                    talk_active = false;
                }
                ESP_LOGW(TAG, "BOOT held: clearing WiFi creds, rebooting to setup");
                ubo_net_creds_clear();
                esp_restart();
            }
        } else {
            if (boot_pressed_prev) {
                if (talk_active) {
                    ubo_client_talk_stop();
                    talk_active = false;
                } else if (!boot_reset_fired && boot_held_ms < TALK_HOLD_MS) {
                    ubo_client_enqueue_key("HOME");
                }
            }
            boot_held_ms = 0;
            boot_reset_fired = false;
        }
        boot_pressed_prev = boot_pressed;

#if MUTE_GPIO >= 0
        /* Mute button -> "M" -> AudioToggleMuteStatusAction(INPUT) (keymap.c).
         * On the ESP32-S3-BOX-3 this pin is a logic-gate output reflecting mute
         * *state* rather than a plain momentary contact, so act on the
         * transition into the asserted level, not on the level itself. */
        const bool mute_pressed = gpio_get_level(MUTE_GPIO) == 0;
        if (mute_pressed && !mute_pressed_prev) {
            ubo_client_enqueue_key("M");
        }
        mute_pressed_prev = mute_pressed;
#endif

        vTaskDelay(pdMS_TO_TICKS(POLL_MS));
    }
}

void ubo_input_start(esp_lcd_touch_handle_t touch) {
    if (xTaskCreate(input_task, "ubo_input", 4096, touch, 5, NULL) != pdPASS) {
        ESP_LOGE(TAG, "input task creation failed");
        return;
    }
    ESP_LOGI(TAG, "touch + BOOT input started");
}
