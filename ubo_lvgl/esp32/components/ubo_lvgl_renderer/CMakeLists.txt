# ESP-IDF component wrapper for the shared C renderer (ubo_lvgl/src + include).
# Compiles the platform-neutral renderer + the esp_lcd display backend; excludes
# the SDL / ST7789 / sim / snapshot-main desktop-only sources. The desktop
# CMake build is untouched.
set(UBO_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../..")
set(UBO_SRC "${UBO_ROOT}/src")
set(UBO_INC "${UBO_ROOT}/include")

idf_component_register(
    SRCS
        "${UBO_SRC}/ubo_lvgl.c"
        "${UBO_SRC}/display/backend_esp_lcd.c"
        "${UBO_SRC}/display/backend_buffer.c"
        "${UBO_SRC}/fonts/fonts_runtime.c"
        "${UBO_SRC}/fonts/ubo_icon_18.c"
        "${UBO_SRC}/fonts/ubo_icon_14.c"
        "${UBO_SRC}/fonts/ubo_icon_24.c"
        "${UBO_SRC}/fonts/ubo_icon_32.c"
        "${UBO_SRC}/views/item_bar.c"
        "${UBO_SRC}/views/overlays.c"
        "${UBO_SRC}/views/screen.c"
        "${UBO_SRC}/views/view_application.c"
        "${UBO_SRC}/views/view_chat.c"
        "${UBO_SRC}/views/view_home.c"
        "${UBO_SRC}/views/view_instruction.c"
        "${UBO_SRC}/views/view_menu.c"
        "${UBO_SRC}/views/view_notification.c"
        "${UBO_SRC}/views/view_prompt.c"
        "${UBO_SRC}/views/view_render.c"
    INCLUDE_DIRS
        "${UBO_INC}"
        "${UBO_SRC}"
    REQUIRES
        lvgl
        esp_lcd
)

# Build the esp_lcd backend. Geometry/fonts are RESPONSIVE — derived at runtime
# from the panel size (ubo_layout_init, scale = height/240) — so no per-dimension
# overrides are needed here, and one component serves every board: ubo_lvgl_init
# is called with BOARD_LCD_H_RES x BOARD_LCD_V_RES (368x448 on the C6 AMOLED,
# 320x240 on the ESP32-S3-BOX-3). The panel-family differences live in the
# ubo_backend_esp_lcd_cfg that board.c supplies.
target_compile_definitions(${COMPONENT_LIB} PRIVATE UBO_WITH_ESP_LCD=1)
