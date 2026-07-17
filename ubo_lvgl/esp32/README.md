# ubo_lvgl on ESP32-C6-Touch-AMOLED-1.8 (ESP-IDF)

Native firmware that runs the **C LVGL renderer + web-grpc client** on the
Waveshare **ESP32-C6-Touch-AMOLED-1.8** (SH8601 368×448 AMOLED over QSPI, FT3168
touch, WiFi 6). This is **additive** — the desktop (SDL) and Raspberry Pi (ST7789)
builds under `ubo_lvgl/` are untouched; this tree is only consumed by `idf.py`.

> ESP32-C6: single-core RISC-V @160MHz, **512KB SRAM, no PSRAM**, 16MB flash.
> Memory is tight — the camera viewfinder is deferred; transport is plain HTTP.

## Flash from your browser (no toolchain required)

Every release ships a prebuilt firmware image — no ESP-IDF install needed:

1. Download `ubo-lvgl-esp32c6-<version>-merged.bin` from the repo's
   [GitHub Releases](https://github.com/ubopod/ubo_app/releases) page.
2. Connect the board over USB and open
   [ESPConnect](https://thelastoutpostworkshop.github.io/ESPConnect/) in a
   browser with Web Serial support (Chrome or Edge), then select the board's
   serial port.
3. In the **Flash** tab: choose the downloaded `.bin`, set the offset to
   **`0x0`**, enable **Erase before flash**, and flash.
4. After the reboot, join the `ubo-setup` WiFi AP to provision your network and
   ubo-core endpoint — see [WiFi setup (captive portal)](#wifi-setup-captive-portal).

The merged image bundles the bootloader, partition table, and app, so `0x0` is
the only offset you need. **Compatibility:** the client's protobuf schema must
match the ubo-core it connects to — flash the firmware release that corresponds
to your installed ubo-app version.

CI builds the image on every push — the `esp32` job in
`.github/workflows/integration_delivery.yml` (equivalent to
`idf.py build && idf.py merge-bin`) — so the firmware artifact always comes
from the same commit, version, and release as the ubo_app packages it must
stay proto-compatible with.

## Board pin map (fixed)

| Function | GPIO |
|---|---|
| LCD QSPI (SPI2): CS / PCLK / D0 / D1 / D2 / D3 | 5 / 0 / 1 / 2 / 3 / 4 |
| LCD reset | via TCA9554 IO-expander (pins 4,5) |
| Touch I2C0: SCL / SDA / INT | 7 / 8 / 15 (INT unused; polled at 50Hz) |
| BOOT button | 9 (active low → tap = HOME; hold ~8s = clear saved WiFi) |

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
button (GPIO9) for ~8 seconds**. That erases the stored WiFi + endpoint and reboots
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

## PPP over USB (the Ubo Pod build)

There are **two build profiles**. The default one above is WiFi-only and keeps
its log console on USB. The `.ppp` profile instead carries gRPC-Web traffic to
ubo-core over the **USB cable itself**, as a PPP link — an lwIP PPP client on the
board, `pppd` on the Pi.

The C6 has no USB-OTG (its only USB is the fixed-function Serial/JTAG CDC-ACM
controller), so USB-Ethernet is impossible and PPP is the way to get IP over the
wire. Envoy already binds `0.0.0.0:50052` in the Pi's host netns, so `10.66.0.1`
reaches it with no forwarding and **no core-side change at all**.

```bash
# sdkconfig.defaults* is only read when sdkconfig is absent — remove it first,
# or the new keys are silently ignored.
rm -f sdkconfig
idf -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.ppp" build
```

> **This profile has no USB logs.** PPP must own the USJ endpoint, so
> `CONFIG_ESP_CONSOLE_SECONDARY_NONE=y` and `idf monitor` over the cable shows
> nothing. The primary console is still UART0. Flashing is unaffected (esptool
> uses ROM download mode). Debug on the default profile; ship the `.ppp` one.

Pi side (installed by `ubo-bootstrap`): `ubo_app/system/udev/99-ubo-esp32-ppp.rules`
symlinks the board to `/dev/ubo-esp32` and device-activates
`ubo-esp32-ppp.service`, which runs `pppd` with `10.66.0.1:10.66.0.2`. Plug the
board in and the link comes up; unplug it and the unit stops.

**Flashing a board that is cabled to a running Pi:** use `./flash.sh`, not bare
`esptool`. `pppd` holds the port open, and esptool re-enumerates it mid-flash —
which retriggers udev and would restart `pppd` into the flashing session. The
script masks the unit for the duration.

Transport selection at boot: if a USB host is present (SOF packets — a bare
charger sends none, so power-only cabling costs nothing) and the stored
preference isn't `wifi`, the board comes up on PPP and **never initializes WiFi
at all**. It then retries the link forever rather than demoting itself, so a Pi
reboot is ridden out. To move between links, tap the **Use WiFi** / **Use USB**
button on the disconnect overlay — it persists the choice and reboots (the
client's base URL is fixed at creation, so switching link means starting over).
WiFi credentials are kept throughout, so switching to WiFi does not re-run the
captive portal. The 8s BOOT hold clears creds *and* the transport preference.

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
  horizontal swipe → BACK, BOOT tap → HOME, BOOT hold ~8s → clear WiFi creds +
  transport preference and reboot to setup, slide/tap the home volume bar → set
  volume, tap the transport switch on the disconnect overlay → change link + reboot.
- **captive portal** (only when WiFi can't be joined) → SoftAP + DNS + HTTP form on
  `provisioning.c`; submitting creds saves them to NVS and reboots.

## Firmware architecture

For contributors: the firmware is a plain **ESP-IDF v6 / FreeRTOS** application
— no custom scheduler, no bare-metal loops. The ESP32-C6 is single-core, so
FreeRTOS time-slices all tasks on one RISC-V hart; "parallel" below means
concurrent, not simultaneous.

### Source layout (`main/`)

| File | Responsibility |
|---|---|
| `ubo_app_main.c` | `app_main` entry point: board bring-up, renderer init, transport selection (USB/PPP or WiFi), then start client + input (or the captive portal) |
| `board.c` | I2C bus, SH8601 QSPI panel, FT3168 touch, TCA9554 IO-expander (LCD reset, speaker amp) |
| `client_app.c` | The gRPC-Web client: store/event stream tasks, dispatch worker, push-to-talk mic handoff |
| `input.c` | Touch + BOOT button polling, gesture classification → Ubo keys |
| `audio.c` | ES8311 codec over I2S: playback ring + task, mic capture task |
| `net.c` | WiFi STA join, NVS persistence of creds + core endpoint + transport preference |
| `usb_ppp.c` | PPP/IP over USB Serial/JTAG: USJ driver, esp_netif PPP glue, RX pump, link state (`.ppp` profile only) |
| `provisioning.c` | Captive portal: SoftAP + DNS catch-all + HTTP setup form |

The renderer itself (LVGL widget tree, view translation, status bar) is **not**
in this tree — it's the shared C renderer in `ubo_lvgl/src/`, compiled in as a
component. Same for the transport (`ubo_lvgl/client/` via `client_core.c` /
`ubo_rpc.h`) and the curated nanopb proto. This tree only contains what is
ESP32-specific.

### Boot sequence (`app_main`)

1. Board bring-up: I2C → SH8601 panel → FT3168 touch.
2. Audio init (ES8311 + full-duplex I2S) — non-fatal; UI runs without it.
3. Renderer init on the SH8601 backend (splash shows until the first view).
4. Spawn the `lvgl` task — the render loop runs from here on.
5. `ubo_net_init_base()`: NVS + netif + event loop — needed by either transport.
6. **USB** (`.ppp` profile, preference not `wifi`, USB host attached): start the
   input task, offer the *Use WiFi* switch, and hand the link to `usb_link_task`,
   which negotiates PPP, starts the client on the first `GOT_IP`, and thereafter
   keeps the link alive forever. WiFi is never initialized. Otherwise →
7. **WiFi** (`ubo_net_wifi_init()`): NVS creds first, else the Kconfig seed. On
   success → start the three client tasks + the input task. On failure → run the
   captive portal (blocks; reboots after provisioning).

### FreeRTOS tasks

| Task | Created in | Stack | Prio | Role |
|---|---|---|---|---|
| `main` | ESP-IDF | 8192 | 1 | `app_main`; becomes the portal server in setup mode |
| `lvgl` | `ubo_app_main.c` | 12288 | 5 | `ubo_lvgl_run()`: `lv_timer_handler` + panel flushes. Stack-hungry (font rendering) |
| `ubo_store` | `client_app.c` | 8192 | 5 | Store stream subscription (`current_view`, `status_bar`, `is_blanked`) → renderer; reconnect with backoff |
| `ubo_event` | `client_app.c` | 6144 | 5 | Event stream: scroll / menu-choose / audio playback events; reconnect with backoff |
| `ubo_disp` | `client_app.c` | 4096 | 5 | Dispatch worker — the **single HTTP-request owner** (see below) |
| `ubo_input` | `input.c` | 4096 | 5 | Polls touch + BOOT at 50Hz; classifies tap/swipe/hold → keys |
| `ubo_mic` | `audio.c` | 4096 | 6 | Push-to-talk capture: 16kHz mono frames → chunk callback. Spawned on talk start, deletes itself on stop |
| `ubo_play` | `audio.c` | 4096 | 5 | Drains the playback ring into the codec; manages rate switches + idle close |
| `usb_link` | `ubo_app_main.c` | 3072 | 5 | *(`.ppp` profile, USB mode)* Owns the PPP link: negotiate → start client once → wait for link-down → retry forever |
| `usb_ppp_rx` | `usb_ppp.c` | 3072 | 5 | *(`.ppp` profile, USB mode)* Pumps bytes off the USJ endpoint into lwIP's PPP input |

### Concurrency model

**All outgoing RPC is serialized on `ubo_disp`.** The other tasks never issue
HTTP requests directly — they hand work to the dispatch worker instead, which
keeps push-to-talk ordering (`start → samples → stop`) intact and avoids
concurrent use of one HTTP client:

- **Key presses** — `ubo_input` → `ubo_client_enqueue_key()` → a FreeRTOS
  queue (16 × 8-byte entries) drained by `ubo_disp`.
- **Volume** — coalesced through a single `s_pending_vol` slot; a slide
  produces one in-flight set-volume at a time, always the latest value.
- **Talk transitions** — `s_talk_cmd` (start/stop) is polled by `ubo_disp`,
  which starts/stops the mic and sends the assistant actions.
- **Mic chunks** — `ubo_mic`'s callback copies each chunk into one of two
  pre-wrapped ping-pong buffers and publishes its index under a mutex
  (drop-oldest, never blocks capture); `ubo_disp` drains and sends it.

**LVGL is guarded by one global mutex** (`ubo_lock` in `ubo_lvgl/src/ubo_lvgl.c`
— a pthread mutex, mapped to FreeRTOS by ESP-IDF's pthread layer). The `lvgl`
task holds it around `lv_timer_handler`; every public `ubo_lvgl_*` call takes
it, so `ubo_store` / `ubo_event` can update the widget tree from their own
tasks. Never touch `lv_*` APIs directly from another task without it.

**Audio** has its own mutex (`a.lock`) serializing codec open/close and mode
transitions. Playback bytes flow through a 16KB FreeRTOS stream buffer (~0.5s
at 16kHz mono; smooths HTTP jitter) drained by `ubo_play`. Mic capture and
playback are mutually exclusive: a talk session closes the output and discards
queued audio.

### Memory budget

512KB SRAM, **no PSRAM** — every buffer above is sized against this. Healthy
figures: ~314KB free heap at boot, ~205KB after renderer-up. When adding code,
prefer static buffers with explicit sizes over heap growth, and check
`uxTaskGetStackHighWaterMark()` before raising a task stack. A silent reboot
with no panic output is usually a task stack overflow.

## Status

All phases complete and verified on-device:

- **P0 — first light:** board bring-up + color-band test pattern over QSPI. ✅
- **P1 — renderer:** responsive 368×448 layout (`scale = h/240`). ✅
- **P2 — transport:** WiFi + `esp_http_client` gRPC-Web. ✅
- **P3 — live UI:** store/event streams drive the renderer live. ✅
- **P4 — touch:** FT3168 tap/swipe + BOOT + interactive volume bar. ✅
- **P5 — resilience:** reconnect/backoff, disconnect overlay, blanking. ✅
- **P6 — provisioning:** WiFi captive portal (SoftAP + DNS + scan form) + optional
  ubo-core endpoint fields, NVS-persisted, BOOT-hold (~8s) reset. ✅
