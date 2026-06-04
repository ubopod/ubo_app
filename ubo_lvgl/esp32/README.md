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
| BOOT button | 9 (active low → tap = HOME; hold ~3s = clear saved WiFi) |

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

The core's gRPC-Web endpoint is baked in at build time via Kconfig
(`main/Kconfig.projbuild`); WiFi credentials can be baked in too, **or** entered
on the device via the captive portal (see below). Set values with `menuconfig` →
**Ubo LVGL Client**:

- `UBO_CORE_GRPC_WEB_URL` — `http://<host-lan-ip>:50052/grpc` (plain HTTP, no TLS).
- `UBO_WIFI_SSID` / `UBO_WIFI_PASSWORD` — *optional* build-time seed for the 2.4GHz
  network. Leave at the `changeme` default to provision over the portal instead.
- `UBO_WIFI_CONNECT_TIMEOUT_S` (default 5) — wait before falling back to the portal.
- `UBO_PROV_AP_SSID` (default `ubo-setup`) — the open SoftAP used for provisioning.

```bash
cd ubo_lvgl/esp32
idf menuconfig   # writes sdkconfig (gitignored)
```

## WiFi setup (captive portal)

The device can be put on a network entirely from a phone — no re-flash, no serial
console. This is the **WiFi setup journey**:

1. **Power on.** The panel shows the `ubo` splash while it tries to join a known
   network: saved credentials from NVS first, then the build-time Kconfig seed.
2. **No network → setup mode.** If it can't connect within
   `UBO_WIFI_CONNECT_TIMEOUT_S` (default 5s) — no creds yet, wrong password, or out
   of range — it opens an **open WiFi access point named `ubo-setup`** and the panel
   shows *"WiFi setup — Join 'ubo-setup' then open http://192.168.4.1"*.
3. **Join `ubo-setup`** from a phone or laptop. The OS captive-portal check pops the
   setup page automatically; if it doesn't, open `http://192.168.4.1` in a browser.
4. **Fill in the form:**
   - **Network** — pick your WiFi from the scanned dropdown.
   - **Password** — your WiFi password.
   - **Ubo hostname/IP** *(optional)* — where ubo-core runs; leave blank if unsure.
   - **Port** *(optional)* — gRPC-Web port, pre-filled `50052`.
5. **Connect.** The device saves everything to NVS, shows *"Saved — rebooting"*, and
   restarts. It now boots straight onto your network and renders the live ubo-core UI.

**Re-provisioning / moving networks:** while the device is running, **hold the BOOT
button (GPIO9) for ~3 seconds**. That erases the stored WiFi + endpoint and reboots
into `ubo-setup` so you can set them again. (A short BOOT tap is still HOME.)

### Notes

- The DNS catch-all that makes the page auto-open is vendored in-tree under
  `components/dns_server/` (from the ESP-IDF captive_portal example).
- The optional endpoint fields build `http://<host>:<port>/grpc`, which **overrides**
  the Kconfig `UBO_CORE_GRPC_WEB_URL`. Left blank, host defaults to `0.0.0.0` and port
  to `50052`. They persist in NVS beside the WiFi creds and clear together on reset.

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
368×448, then resolves WiFi creds (NVS → Kconfig seed) and tries to join. On
success it starts the client tasks (`client_app.c`) and the touch input task
(`input.c`); on failure it runs the captive portal (`provisioning.c`) instead:

- **store stream** → `view_translate` → renderer (current view + status bar +
  blanking), with exponential-backoff reconnect and a disconnect overlay + countdown.
- **event stream** → local scroll / menu-choose on the active render widget
  (the camera viewfinder is deferred — no `frame_stream` subscription).
- **dispatch worker** → keypad actions + coalesced volume sets.
- **touch/BOOT input** → tap a drawn item slot → L1/L2/L3, vertical swipe → UP/DOWN,
  horizontal swipe → BACK, BOOT tap → HOME, BOOT hold ~3s → clear WiFi + reboot to
  setup, slide/tap the home volume bar → set volume.
- **captive portal** (only when WiFi can't be joined) → SoftAP + DNS + HTTP form on
  `provisioning.c`; submitting creds saves them to NVS and reboots.

## Status

All phases complete and verified on-device:

- **P0 — first light:** board bring-up + color-band test pattern over QSPI. ✅
- **P1 — renderer:** responsive 368×448 layout (`scale = h/240`). ✅
- **P2 — transport:** WiFi + `esp_http_client` gRPC-Web. ✅
- **P3 — live UI:** store/event streams drive the renderer live. ✅
- **P4 — touch:** FT3168 tap/swipe + BOOT + interactive volume bar. ✅
- **P5 — resilience:** reconnect/backoff, disconnect overlay, blanking. ✅
- **P6 — provisioning:** WiFi captive portal (SoftAP + DNS + scan form) + optional
  ubo-core endpoint fields, NVS-persisted, BOOT-hold (~3s) reset. ✅
