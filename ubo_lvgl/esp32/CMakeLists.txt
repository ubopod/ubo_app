# ESP-IDF project for the Waveshare ESP32-C6-Touch-AMOLED-1.8.
# Additive: the desktop (SDL) and Raspberry Pi (ST7789) GUI builds are untouched;
# this tree is only consumed by `idf.py`.
cmake_minimum_required(VERSION 3.16)

# The LVGL 9.3 submodule (builds as the `lvgl` component via its ESP-IDF support,
# picking up ubo_lvgl/lv_conf.h) and the shared-renderer component wrapper.
set(EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/../lvgl"
    "${CMAKE_CURRENT_LIST_DIR}/components/ubo_lvgl_renderer"
    "${CMAKE_CURRENT_LIST_DIR}/components/ubo_client_core")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# Force LVGL to use OUR lv_conf.h. The ESP component defaults to
# CONFIG_LV_CONF_SKIP=1 (Kconfig-driven config), which would drop our font set
# and widget choices. LV_CONF_PATH overrides the skip (lv_conf_internal.h) and
# includes our config by absolute path, build-wide (lvgl + renderer).
idf_build_set_property(COMPILE_OPTIONS
    "-DLV_CONF_PATH=\"${CMAKE_CURRENT_LIST_DIR}/../lv_conf.h\"" APPEND)

project(ubo_lvgl_esp32c6)
