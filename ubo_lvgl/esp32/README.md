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
| Touch I2C0: SCL / SDA / INT | 7 / 8 / 15 (INT unused; polled at 50Hz) |
| BOOT button | 9 (active low → HOME) |

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

## Configure (WiFi + core URL)

WiFi credentials and the core's gRPC-Web endpoint are baked in at build time via
Kconfig (`main/Kconfig.projbuild`). Set them once with `menuconfig` →
**Ubo LVGL Client**:

- `UBO_WIFI_SSID` / `UBO_WIFI_PASSWORD` — the 2.4GHz network (the C6 radio is 2.4GHz).
- `UBO_CORE_GRPC_WEB_URL` — `http://<host-lan-ip>:50052/grpc` (plain HTTP, no TLS).

```bash
cd ubo_lvgl/esp32
idf menuconfig   # writes sdkconfig (gitignored)
```

## Build / flash / monitor

```bash
cd ubo_lvgl/esp32
idf set-target esp32c6        # once (fetches managed components)
idf build
idf -p /dev/cu.usbmodemXXXX flash monitor   # board on USB; Ctrl-] to exit monitor
```

`idf` with no `-p` auto-detects the port. Exit the serial monitor with `Ctrl-]`.

## How it runs

`ubo_app_main.c` brings up the board (`board.c`), the responsive renderer at
368×448, joins WiFi, then starts the client tasks (`client_app.c`) and the touch
input task (`input.c`):

- **store stream** → `view_translate` → renderer (current view + status bar +
  blanking), with exponential-backoff reconnect and a disconnect overlay + countdown.
- **event stream** → local scroll / menu-choose on the active render widget
  (the camera viewfinder is deferred — no `frame_stream` subscription).
- **dispatch worker** → keypad actions + coalesced volume sets.
- **touch/BOOT input** → tap a drawn item slot → L1/L2/L3, vertical swipe → UP/DOWN,
  horizontal swipe → BACK, BOOT → HOME, slide/tap the home volume bar → set volume.

## Status

All phases complete and verified on-device:

- **P0 — first light:** board bring-up + color-band test pattern over QSPI. ✅
- **P1 — renderer:** responsive 368×448 layout (`scale = h/240`). ✅
- **P2 — transport:** WiFi + `esp_http_client` gRPC-Web. ✅
- **P3 — live UI:** store/event streams drive the renderer live. ✅
- **P4 — touch:** FT3168 tap/swipe + BOOT + interactive volume bar. ✅
- **P5 — resilience:** reconnect/backoff, disconnect overlay, blanking. ✅
