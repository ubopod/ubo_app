idf_component_register(
    SRCS
        "ubo_app_main.c"
        "board.c"
        "net.c"
        "client_app.c"
    INCLUDE_DIRS "."
    REQUIRES
        ubo_lvgl_renderer
        ubo_client_core
        esp_lcd
        esp_wifi
        esp_event
        nvs_flash
)
