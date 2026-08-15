/**
 * @file input.h
 * Touch + BOOT-button input: classifies FT3168 gestures into Ubo keypad keys
 * and enqueues them via the web-grpc client (ubo_client_enqueue_key).
 */
#ifndef UBO_INPUT_H
#define UBO_INPUT_H

#include "esp_lcd_touch.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Spawn the input task. `touch` is the FT3168 handle from board_touch_init(). */
void ubo_input_start(esp_lcd_touch_handle_t touch);

#ifdef __cplusplus
}
#endif
#endif /* UBO_INPUT_H */
