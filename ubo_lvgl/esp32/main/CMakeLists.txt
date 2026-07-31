# Board selection is driven off IDF_TARGET, NOT off CONFIG_UBO_BOARD_*.
#
# ESP-IDF evaluates every component CMakeLists.txt twice, and in the early
# requirements-expansion pass Kconfig has not run yet — every CONFIG_* is
# undefined. Gating REQUIRES on a Kconfig symbol therefore silently drops the
# component and fails later with a missing header. (Same class of bug as the
# esp_http_client note in components/ubo_client_core/CMakeLists.txt.)
# IDF_TARGET is set before project() and is stable across both passes, and
# board <-> chip is 1:1 here, so it is an exact selector. CONFIG_UBO_BOARD_*
# still exists for board tuning and is asserted for consistency below.
if(IDF_TARGET STREQUAL "esp32s3")
    set(BOARD_DIR "boards/esp_box_3")
    # esp-sr: AFE speech front end for the two-mic array (Kconfig-gated on
    # SPIRAM at runtime; the component is S3-only via idf_component.yml rules).
    set(BOARD_REQUIRES esp_lcd_ili9341 esp_lcd_touch_gt911 esp_driver_ledc esp-sr)
elseif(IDF_TARGET STREQUAL "esp32c6")
    set(BOARD_DIR "boards/waveshare_c6_amoled")
    set(BOARD_REQUIRES esp_lcd_sh8601 esp_lcd_touch_ft5x06 esp_io_expander_tca9554)
else()
    message(FATAL_ERROR
        "ubo-lvgl: unsupported IDF_TARGET '${IDF_TARGET}'. "
        "Run `idf.py set-target esp32c6` (Waveshare C6 AMOLED) or "
        "`idf.py set-target esp32s3` (ESP32-S3-BOX-3) first.")
endif()

idf_component_register(
    SRCS
        "ubo_app_main.c"
        "${BOARD_DIR}/board.c"
        "net.c"
        "client_app.c"
        "input.c"
        "provisioning.c"
        "audio.c"
        "usb_ppp.c"
    INCLUDE_DIRS "." "${BOARD_DIR}"
    REQUIRES
        ubo_lvgl_renderer
        ubo_client_core
        esp_lcd
        esp_lcd_touch
        esp_driver_gpio
        esp_driver_i2c
        esp_driver_i2s
        esp_driver_spi
        esp_driver_usb_serial_jtag
        esp_codec_dev
        esp_wifi
        esp_event
        esp_netif
        esp_http_server
        dns_server
        nvs_flash
        mbedtls
        ${BOARD_REQUIRES}
)

# Late consistency check. CONFIG_* only exist in the second pass, so this is
# inert during requirements expansion and fires only on a genuine mismatch
# (e.g. a hand-edited sdkconfig).
if(CONFIG_UBO_BOARD_ESP_BOX_3 AND NOT IDF_TARGET STREQUAL "esp32s3")
    message(FATAL_ERROR "CONFIG_UBO_BOARD_ESP_BOX_3 requires IDF_TARGET=esp32s3")
endif()
if(CONFIG_UBO_BOARD_WAVESHARE_C6_AMOLED AND NOT IDF_TARGET STREQUAL "esp32c6")
    message(FATAL_ERROR
        "CONFIG_UBO_BOARD_WAVESHARE_C6_AMOLED requires IDF_TARGET=esp32c6")
endif()
