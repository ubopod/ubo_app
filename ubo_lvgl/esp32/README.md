# ubo_lvgl on ESP32 (ESP-IDF)

Native firmware that runs the **C LVGL renderer + ubo-core client** on a
supported ESP32 board. This is **additive** — the desktop (SDL) and Raspberry Pi
(ST7789) builds under `ubo_lvgl/` are untouched; this tree is only consumed by
`idf.py`.

## Supported boards

| | Waveshare **ESP32-C6-Touch-AMOLED-1.8** | Espressif **ESP32-S3-BOX-3** |
|---|---|---|
| Chip | C6, single-core RISC-V @160MHz | S3, dual-core Xtensa @240MHz |
| RAM | **512KB SRAM, no PSRAM** | 512KB SRAM + **16MB octal PSRAM** |
| Flash | 16MB | 16MB |
| Panel | SH8601 368×448 AMOLED, QSPI | ILI9341-family 320×240 LCD, SPI3 @40MHz, BGR |
| Touch | FT3168 (FT5x06 driver) | GT911 (probes 0x5D, falls back to 0x14) |
| Audio out | ES8311, amp on TCA9554 pin 7 | ES8311, amp on GPIO46 |
| Audio in | ES8311 ADC, 1 mic | **ES7210 ADC, 2 mics** |
| Buttons | BOOT (GPIO9) | BOOT (GPIO0), Mute (GPIO1) |
| Viewfinder | low-res chunked only | low-res **+ full-res** (needs PSRAM) |
| USB/PPP profile | yes (the Ubo Pod build) | yes |

Both boards build from this one tree. `main/CMakeLists.txt` selects the board
sources and driver components from **`IDF_TARGET`** — deliberately *not* from
`CONFIG_UBO_BOARD_*`, because ESP-IDF's early requirements-expansion pass runs
before Kconfig, so every `CONFIG_*` is undefined there and gating `REQUIRES` on
one silently drops the component. The Kconfig choice exists for board tuning and
asserts consistency.

Board specifics live in `main/boards/<board>/`:

| File | Contents |
|---|---|
| `board_pins.h` | Panel geometry, every GPIO, touch orientation flags, gesture thresholds, draw-buffer sizing |
| `board.c` | I2C, panel bring-up + esp_lcd backend handoff, touch, speaker amp, codec construction |

Everything else in `main/` is board-neutral and reads those constants through
`board.h`. The renderer is untouched by board choice: geometry and fonts are
derived at runtime from the panel size (`ubo_layout_init`, `scale = height/240`),
so 320×240 reproduces the 240×240 Pi reference exactly and simply gets wider
menu bars.

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

## Board pin maps (fixed)

### Waveshare ESP32-C6-Touch-AMOLED-1.8

| Function | GPIO |
|---|---|
| LCD QSPI (SPI2): CS / PCLK / D0 / D1 / D2 / D3 | 5 / 0 / 1 / 2 / 3 / 4 |
| LCD reset | via TCA9554 IO-expander (pins 4,5) |
| Speaker amp enable | TCA9554 IO-expander pin 7 |
| Touch I2C0: SCL / SDA / INT | 7 / 8 / 15 (INT unused; polled at 50Hz) |
| I2S: MCLK / BCLK / WS / DOUT / DIN | 19 / 20 / 22 / 23 / 21 |
| BOOT button | 9 (active low → tap = HOME; hold ~8s = clear saved WiFi) |

### Espressif ESP32-S3-BOX-3

| Function | GPIO |
|---|---|
| LCD SPI3: PCLK / DATA0 / CS / DC | 7 / 6 / 5 / 4 |
| LCD reset | 48 — **active high**, and shared with the touch controller |
| LCD backlight | 47 (LEDC PWM, 5kHz, 10-bit) |
| Touch I2C0: SDA / SCL / INT | 8 / 18 / 3 |
| I2S: MCLK / SCLK / LCLK / DOUT / DSIN | 2 / 17 / 45 / 15 / 16 |
| Speaker amp enable | 46 (plain GPIO) |
| BOOT / config button | 0 (active low → tap = HOME; hold ~8s = clear saved WiFi) |
| Mute button | 1 (logic-gate *state* line → `M` → toggle mic mute) |

> The BOX-3's panel init writes MADCTL `0x08` (BGR, MV=0) and the die is
> natively landscape, so 320 columns work with no `swap_xy` — only
> `esp_lcd_panel_mirror(true, true)`. The older ESP-BOX / BOX-3B pairs an
> ST7789 with a TT21100 touch controller instead; `board_display_init()` probes
> I2C 0x24 and logs a loud error if it finds one, since this build carries only
> the BOX-3 driver.
>
> **Infrared is not on the BOX-3 main unit.** The emitter/receiver live on the
> separate ESP32-S3-BOX-3-SENSOR dock, reached through the PCIe connector:
> TX=39, RX=38, CTRL=44. Note GPIO44 is UART0 RX by default, so wiring IR up
> means moving or dropping the UART console first. See "Infrared" below.

## Toolchain environment (EIM install)

The **poe tasks below resolve all of this themselves** — reach for the raw
`idf.py` prefix only when you need an action they don't wrap.

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

From the repo root, the poe tasks handle the toolchain environment, the
per-board build dir and sdkconfig, and the one-time `set-target`:

```bash
uv run poe esp32:build   --board c6                        # or --board s3
uv run poe esp32:flash   --board s3 --port /dev/cu.usbmodem1101
uv run poe esp32:monitor --board c6                        # Ctrl-] to exit
```

| Arg | Default | Meaning |
|---|---|---|
| `--board` | *required* | `c6` = Waveshare C6 AMOLED, `s3` = ESP32-S3-BOX-3 |
| `--profile` | `ppp` | `ppp` = the shipping USB/PPP build (**no USB console**, so `esp32:monitor` shows nothing); `wifi` = the debug build |
| `--port` | auto-detect | Pass it when both boards are plugged in |
| `--transport` | build default (`tcp_lite`) | `-DUBO_TRANSPORT`; sticks in the build dir's CMake cache once set |
| `--fresh` | off | Delete the build dir **and sdkconfig** first — needed after editing a checked-in `sdkconfig.defaults*`, since those are only read when the sdkconfig is absent. Discards anything you set with `menuconfig`. |

Each `(board, profile)` pair gets its own `build.<target>[.ppp]` and
`sdkconfig.<target>[.ppp]`, so the two boards never clobber each other and each
sdkconfig only ever comes from one defaults list. `esp32:flash` builds first.
`scripts/esp32.sh` is the implementation; anything it doesn't wrap (`menuconfig`,
`merge-bin`, `fullclean`) needs the raw `idf` prefix below.

The rest of this section is what those tasks do underneath.

`CONFIG_IDF_TARGET` is **not** pinned in `sdkconfig.defaults` (per-chip settings
live in `sdkconfig.defaults.<target>`, which ESP-IDF appends automatically), so
`set-target` is a required first step rather than an optional one.

```bash
cd ubo_lvgl/esp32

# Waveshare C6 AMOLED
idf set-target esp32c6        # once (fetches managed components)
idf build
idf -p /dev/cu.usbmodemXXXX flash monitor   # Ctrl-] to exit monitor
```

To keep both boards buildable side by side, give each its own build directory
and sdkconfig — otherwise `set-target` wipes the other board's build:

```bash
# Espressif ESP32-S3-BOX-3, without disturbing the C6 build
idf -B build.esp32s3 -D SDKCONFIG=sdkconfig.esp32s3 set-target esp32s3
idf -B build.esp32s3 -D SDKCONFIG=sdkconfig.esp32s3 build
idf -B build.esp32s3 -D SDKCONFIG=sdkconfig.esp32s3 -p /dev/cu.usbmodemXXXX flash
```

`build.*` and `sdkconfig.esp32*` are gitignored. The component manager's
`rules:` in `main/idf_component.yml` mean each target only downloads its own
panel/touch drivers.

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

The profile builds for **both** boards: `usb_ppp.c` talks to the USB Serial/JTAG
peripheral, which the S3 has as well, and `UBO_USB_PPP_ENABLE` depends only on
`LWIP_PPP_SUPPORT`. Nothing in the PPP path is chip-specific.

```bash
# sdkconfig.defaults* is only read when sdkconfig is absent — remove it first,
# or the new keys are silently ignored.
rm -f sdkconfig
idf -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.ppp" build
```

This is what `uv run poe esp32:build --board <c6|s3>` builds by default; it keeps
the profile in its own `sdkconfig.<target>.ppp`, so there is no shared `sdkconfig`
to remove and no way for the two profiles to leak into each other.

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
  (plus low-res `FrameStreamChunkEvent` for the camera viewfinder, and — where
  `CONFIG_UBO_FRAME_STREAM_FULLRES` is available, i.e. on a PSRAM board —
  full-res `FrameStreamDataEvent`).
- **dispatch worker** → keypad actions + coalesced volume sets.
- **touch/BOOT input** → tap a drawn item slot → L1/L2/L3, vertical swipe → UP/DOWN,
  horizontal swipe → BACK, BOOT tap → HOME, BOOT hold ~8s → clear WiFi creds +
  transport preference and reboot to setup, slide/tap the home volume bar → set
  volume, tap the transport switch on the disconnect overlay → change link + reboot.
- **captive portal** (only when WiFi can't be joined) → SoftAP + DNS + HTTP form on
  `provisioning.c`; submitting creds saves them to NVS and reboots.

## Firmware architecture

For contributors: the firmware is a plain **ESP-IDF v6 / FreeRTOS** application
— no custom scheduler, no bare-metal loops. On the ESP32-C6 (single-core)
FreeRTOS time-slices all tasks on one RISC-V hart, so "parallel" below means
concurrent, not simultaneous. **On the dual-core S3 it can mean genuinely
simultaneous**, which matters for the LVGL lock: the discipline below was always
required, but on the C6 a violation could only ever interleave, whereas on the
S3 it can race in parallel. If something looks racy during bring-up, set
`CONFIG_FREERTOS_UNICORE=y` temporarily to reproduce C6 semantics and bisect.

### Source layout (`main/`)

| File | Responsibility |
|---|---|
| `ubo_app_main.c` | `app_main` entry point: board bring-up, renderer init, transport selection (USB/PPP or WiFi), then start client + input (or the captive portal) |
| `board.c` | I2C bus, SH8601 QSPI panel, FT3168 touch, TCA9554 IO-expander (LCD reset, speaker amp) |
| `client_app.c` | The gRPC-Web client: store/event stream tasks, dispatch worker, push-to-talk mic handoff |
| `input.c` | Touch + BOOT button polling, gesture classification → Ubo keys |
| `audio.c` | ES8311 codec over I2S: playback ring + task, mic capture task, esp-sr AFE + WakeNet wake word, and the codec arbitration between them |
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

**ESP32-C6 — 512KB SRAM, no PSRAM.** Every buffer above is sized against this.
Healthy figures: ~314KB free heap at boot, ~205KB after renderer-up. When adding
code, prefer static buffers with explicit sizes over heap growth, and check
`uxTaskGetStackHighWaterMark()` before raising a task stack. A silent reboot
with no panic output is usually a task stack overflow.

**ESP32-S3-BOX-3 — 512KB SRAM + 16MB octal PSRAM.** Far more headroom: ~16.9MB
free heap at boot, ~16.7MB with the captive portal up. `CONFIG_SPIRAM_USE_MALLOC`
routes large `malloc()`s to PSRAM, so LVGL (which is on `LV_STDLIB_CLIB`), the
viewfinder frame buffer in `src/views/view_render.c` and the tcp-lite parser all
benefit with no code change, while `CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL=16384`
keeps small hot allocations in fast internal SRAM.

**Keep LVGL draw buffers out of PSRAM.** `board.c` allocates them
`MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL` on purpose: esp_lcd's SPI DMA wants
cache-line-aligned memory with an explicit writeback, and a PSRAM draw buffer
shows up as 64-byte-periodic stale stripes or tearing that reads like a panel
fault. Spend PSRAM on frame data instead.

## Wake word (ESP32-S3-BOX-3 only)

`CONFIG_UBO_WAKE_ENABLE` runs espressif/esp-sr's **WakeNet** inside the existing
AFE, so the device starts an assistant turn on a spoken phrase instead of only
on a BOOT-button hold. Default **"Jarvis"** (`CONFIG_SR_WN_WN9_JARVIS_TTS`);
`wn9_computer_tts`, `wn9_heywillow_tts` and `wn9_hiesp` are vendored
alternatives, one line apart.

It is S3-only for the same reason the AFE is: the C6 has no PSRAM and one
microphone.

**The pod cannot do this for us.** ubo-core's own wake engines
(`090-speech-recognition`, vosk + openWakeWord) drop every audio sample carrying
an `audio_source`, so a satellite's microphone never reaches them. Detection has
to run here.

### What it changes

- **Capture becomes always-on.** The microphone is open whenever the speaker is
  idle. `audio.c` gains a three-state codec arbitration — `IDLE_WAKE`
  (listening, output discarded) / `STREAMING` (a session, output sent to the
  core) / `PLAYING` (speaker owns the codec) — because the two directions
  cannot both be open: one I2S port, one bit clock, and `esp_codec_dev` rejects
  a paired open at a different sample rate (16kHz capture vs 48kHz TTS).
  `play_task` owns every transition.
- **No barge-in.** The microphone is physically closed while the speaker plays,
  which is also why no echo cancellation is needed to stop the device waking
  itself. It stays deaf for `CONFIG_UBO_WAKE_COOLDOWN_MS` (800ms) after the
  output closes, covering speaker decay and room reverb. Interrupt with BOOT.
- **`PLAY_IDLE_CLOSE_US` drops 2s → 800ms**, so the device is not deaf for two
  seconds after every reply.
- **`ubo_mic` moves to core 1.** WakeNet inference runs inside
  `fetch_with_delay()`, not `feed()`, so it is continuous — and core 0 carries
  WiFi and lwIP.
- **The mute switch closes the microphone**, rather than the core refusing each
  session and answering with a notification and a failure chime. Muting mid-turn
  ends the turn rather than pausing it, and `ubo_audio_mic_start` refuses while
  muted, so nothing local or remote can reopen the mic through an engaged
  switch. Tracks the hardware pin only; a mute applied from the web UI is not
  yet mirrored.
- **Listening is armed only once a client is connected** (`ubo_audio_wake_bind`,
  at the end of `ubo_client_start`). A board sitting in its captive portal never
  opens the microphone — which also matters because the input task that reads
  the mute switch does not exist on that path.
- **A 120 s local watchdog ends a session the core never closed.** Only the core
  ends a wake turn, so a start action that never lands would otherwise leave the
  mic open and every playback chunk refused until reboot.
- **A `model` partition (512KB at `0x410000`) holds `srmodels.bin`.** See the
  flashing warning in `AFE-FAR-FIELD.md` — the partition table and the model
  image must be written in the same operation, and never at `0x0`.

### Wiring to the core

On detection the capture task promotes itself to `STREAMING` **before** telling
the core, so the words after the wake phrase are already buffering while the
dispatch is in flight. It then dispatches `AssistantStartListeningAction`
carrying a `WakePhraseTriggerSource(phrase, detector="wakenet", mode)`.

That trigger source is **not optional metadata**. ubo-core resolves a
turn-completion policy from it; with no `source` it matches none and publishes an
inert policy — no silence stop, no phrase stop. Push-to-talk survives that
because releasing BOOT sends the stop, but a wake-word turn has no release and
would stream until reboot. `CONFIG_UBO_WAKE_MODE` picks the slot
(QUICK_CHAT by default: one short turn, ended by ~2s of silence. CONVERSATION
is the alternative — it tolerates long pauses and ends on an end-of-turn phrase
like "i am done talking" — but it holds the microphone far longer per wake,
which on this board also means the speaker cannot have the codec for that
whole time).

Turn-end is still entirely the core's: it sends
`AssistantRequestMicStreamEvent(is_active=false)`, exactly as for any other
session.

### Checking it works

Boot log should show `wake word: model=wn9_jarvis_tts phrase="Jarvis"`, then
esp-sr's `wakenet is activated, disable WebRTC AGC.`, then a pipeline line from
`print_pipeline()` containing `WakeNet(wn9_jarvis_tts,...)`. Each detection logs
`WAKE: "Jarvis" word=1 ...`.

If no model resolves, `afe_config_check()` clears `wakenet_init` and the device
falls back to the exact push-to-talk-only pipeline — so a missing or unflashed
`model` partition degrades quietly rather than breaking capture. `pcm_config
AFTER check: ... wakenet=0` in the boot log is the tell.

## Infrared (ESP32-S3-BOX-3, not yet implemented)

IR needs the separate **ESP32-S3-BOX-3-SENSOR** dock; the main unit has no
emitter or receiver. Two things make this more than a driver exercise:

1. **GPIO44 (IR CTRL) is UART0 RX by default.** Claiming it means moving the
   console to USB Serial/JTAG or giving it up.
2. **ubo-core's `090-infrared` service is Linux-only.** It sends via `ir-ctl`
   (LIRC) and receives through the privileged system manager — neither is
   reachable from the board. The ESP32 would instead act as an IR transceiver
   *peer*: RMT TX on GPIO39, RMT RX on GPIO38, dispatching
   `InfraredHandleReceivedCodeAction` upstream and consuming
   `InfraredSendCodeEvent` downstream. That requires adding both to the
   **curated** proto (`ubo_lvgl/client/proto/ubo_client.proto`) with oneof tags
   matched exactly to the running core's `ubo_bindings`, then regenerating
   nanopb — the same trap that produced the stale-tag bug in the original C6
   port.

## Status

### Waveshare ESP32-C6-Touch-AMOLED-1.8 — complete, verified on-device

- **P0 — first light:** board bring-up + color-band test pattern over QSPI. ✅
- **P1 — renderer:** responsive 368×448 layout (`scale = h/240`). ✅
- **P2 — transport:** WiFi + `esp_http_client` gRPC-Web. ✅
- **P3 — live UI:** store/event streams drive the renderer live. ✅
- **P4 — touch:** FT3168 tap/swipe + BOOT + interactive volume bar. ✅
- **P5 — resilience:** reconnect/backoff, disconnect overlay, blanking. ✅
- **P6 — provisioning:** WiFi captive portal (SoftAP + DNS + scan form) + optional
  ubo-core endpoint fields, NVS-persisted, BOOT-hold (~8s) reset. ✅

### Espressif ESP32-S3-BOX-3 — bring-up in progress

- **M0 — boots:** octal PSRAM up (16.9MB free heap), reaches `app_main`. ✅
- **M1 — display:** ILI9341 320×240, correct orientation and colors. ✅
- **M2 — renderer:** 320×240 layout (`scale` = 1.0, identical to the Pi
  reference with wider menu bars). ✅
- **M3 — peripherals detected:** GT911 at 0x5D, ES8311 + ES7210 (MIC1+MIC2). ✅
- **M4 — provisioning:** captive portal comes up. ✅
- **M5 — touch input:** tap/swipe → L1/L2/L3, axis orientation. ⏳
- **M6 — live UI over tcp-lite.** ⏳
- **M7 — audio:** chime playback + push-to-talk capture. ⏳ Exercise
  speaker → mic → speaker three times in a row: this SoC generation defers an
  RX disable that would otherwise stop TX, a path the C6 never hits, and the
  symptom is "audio works once, then silence".
- **M8 — full-res viewfinder** (`CONFIG_UBO_FRAME_STREAM_FULLRES`). ⏳
