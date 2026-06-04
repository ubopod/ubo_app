# ubo_lvgl on ESP32-C6-Touch-AMOLED-1.8 (ESP-IDF)

Native firmware that runs the **C LVGL renderer + web-grpc client** on the
Waveshare **ESP32-C6-Touch-AMOLED-1.8** (SH8601 368×448 AMOLED over QSPI, FT3168
touch, WiFi 6). This is **additive** — the desktop (SDL) and Raspberry Pi (ST7789)
builds under `ubo_lvgl/` are untouched; this tree is only consumed by `idf.py`.

> ESP32-C6: single-core RISC-V @160MHz, **512KB SRAM, no PSRAM**, 16MB flash.
> Memory is tight — the camera viewfinder is deferred; transport is plain HTTP.

## Board pin map (fixed)

| Function | GPIO |
|---|---|
| LCD QSPI (SPI2): CS / PCLK / D0 / D1 / D2 / D3 | 5 / 0 / 1 / 2 / 3 / 4 |
| LCD reset | via TCA9554 IO-expander (pins 4,5) |
| Touch I2C0: SCL / SDA / INT | 7 / 8 / 15 |

## Toolchain environment (EIM install)

ESP-IDF **v6.0.1** is installed via EIM with a non-standard layout, so the default
`activate`/`export.sh` alone does not work. Use this prefix for every `idf.py` call:

```bash
source /Users/martin/.espressif/tools/activate_idf_v6.0.1.sh >/dev/null 2>&1
export IDF_PATH=/Users/martin/Documents/Espressif/.espressif/v6.0.1/esp-idf
export IDF_TOOLS_PATH=/Users/martin/.espressif/tools
export IDF_PYTHON_ENV_PATH=/Users/martin/.espressif/tools/python/v6.0.1/venv
export ESP_IDF_VERSION=6.0.1
idf() { "$IDF_PYTHON_ENV_PATH/bin/python" "$IDF_PATH/tools/idf.py" "$@"; }
```

## Build / flash / monitor

```bash
cd ubo_lvgl/esp32
idf set-target esp32c6        # once (fetches managed components)
idf build
idf -p /dev/cu.usbmodemXXXX flash monitor   # board on USB; Ctrl-] to exit monitor
```

`idf` with no `-p` auto-detects the port. Exit the serial monitor with `Ctrl-]`.

## Status

- **Phase 0 (first light):** board bring-up (`board.c`) + a color-band test pattern
  (`ubo_app_main.c`). Verifies QSPI wiring + SH8601 init. ✅ builds
- Phases 1–5 (renderer, WiFi+transport, live UI, touch, resilience): in progress.
