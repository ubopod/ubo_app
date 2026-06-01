cmake_minimum_required(VERSION 3.15)
project(ubo_lvgl C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(UBO_WITH_SDL "Build the SDL desktop backend" ON)
option(UBO_WITH_ST7789 "Build the ST7789 SPI backend (Raspberry Pi)" OFF)

# Point LVGL at our lv_conf.h and trim its demo/example builds.
set(LV_BUILD_CONF_PATH "${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h" CACHE PATH "" FORCE)
set(CONFIG_LV_BUILD_DEMOS OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)

# These must be defined before LVGL is configured so lv_conf.h sees them.
if(UBO_WITH_SDL)
    add_compile_definitions(UBO_WITH_SDL)
    # LVGL's own SDL driver needs the SDL headers, so resolve SDL2 before LVGL.
    find_package(SDL2 REQUIRED)
endif()
if(UBO_WITH_ST7789)
    add_compile_definitions(UBO_WITH_ST7789)
endif()

add_subdirectory(lvgl)

# Give LVGL the SDL include dirs/libs so its src/drivers/sdl/* compiles.
if(UBO_WITH_SDL)
    if(TARGET SDL2::SDL2)
        target_link_libraries(lvgl PUBLIC SDL2::SDL2)
    else()
        target_include_directories(lvgl PUBLIC ${SDL2_INCLUDE_DIRS})
        target_link_libraries(lvgl PUBLIC ${SDL2_LIBRARIES})
    endif()
endif()

# LVGL globs arch-specific assembly (Helium/NEON) blend kernels into its target.
# We use LV_DRAW_SW_ASM_NONE, so these contribute nothing — and they fail to
# assemble on the host (their headers pull in C system headers). Drop them.
get_target_property(_lvgl_srcs lvgl SOURCES)
list(FILTER _lvgl_srcs EXCLUDE REGEX "blend/(helium|neon)/.*\\.S$")
set_target_properties(lvgl PROPERTIES SOURCES "${_lvgl_srcs}")

set(UBO_SOURCES
    src/ubo_lvgl.c
    src/display/backend_sdl.c
    src/display/backend_st7789.c
    src/display/backend_buffer.c
    src/views/screen.c
    src/views/item_bar.c
    src/views/view_menu.c
    src/views/view_home.c
    src/views/view_notification.c
    src/views/view_instruction.c
    src/views/view_prompt.c
    src/views/view_application.c
    src/views/overlays.c
    src/fonts/ubo_icon_18.c
    src/fonts/ubo_icon_14.c
    src/fonts/fonts_runtime.c
)

add_library(ubo_lvgl SHARED ${UBO_SOURCES})
target_include_directories(ubo_lvgl
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(ubo_lvgl PUBLIC lvgl)
target_compile_options(ubo_lvgl PRIVATE -Wall -Wextra)

if(UBO_WITH_SDL)
    find_package(SDL2 REQUIRED)
    if(TARGET SDL2::SDL2)
        target_link_libraries(ubo_lvgl PUBLIC SDL2::SDL2)
    else()
        target_include_directories(ubo_lvgl PRIVATE ${SDL2_INCLUDE_DIRS})
        target_link_libraries(ubo_lvgl PUBLIC ${SDL2_LIBRARIES})
    endif()
endif()

# Desktop simulator executable.
add_executable(ubo_lvgl_sim src/sim_main.c)
target_link_libraries(ubo_lvgl_sim PRIVATE ubo_lvgl)

# Headless snapshot tool (renders to BMP; no display needed).
add_executable(ubo_lvgl_snapshot src/snapshot_main.c)
target_link_libraries(ubo_lvgl_snapshot PRIVATE ubo_lvgl)
