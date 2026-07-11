# Ubo LVGL GUI client

An [LVGL](https://lvgl.io) (C) reimplementation of the Ubo GUI's rendering
layer. It draws the Ubo UI on the 240×240 **ST7789** SPI panel (and on a desktop
**SDL** window for development), replacing the heavier Kivy + headless-kivy
stack. The renderer is a *dumb* client: it subscribes to the core's `ViewData` /
`StatusBarData` over gRPC and draws them — all navigation/menu logic lives in the
core.

It comes in three pieces:

| Piece | Path | Language |
|-------|------|----------|
| Renderer library (`libubo_lvgl`) | `ubo_lvgl/` | C |
| Python gRPC bridge / launcher | `ubo_app/lvgl_gui/ubo_lvgl_gui_client/` | Python |
| Native C web-grpc client (`ubo_lvgl_client`) | `ubo_lvgl/client/` | C |

## Why three pieces (phases)

The C library is the durable artifact. Its public API (`include/ubo_lvgl.h`) is a
*view model* that mirrors the core's `ViewData`/`StatusBarData` field-for-field.

```
        PHASE 1 (Python bridge)              PHASE 2 (native C, this client/)
 ┌──────────────────────────────┐         ┌──────────────────────────────┐
 │ Python: ubo_lvgl_gui_client  │         │ C: ubo_lvgl_client           │
 │  gRPC or web-grpc + reconnect│         │  web-grpc + nanopb decode    │
 │  ViewData ── translate ──┐   │         │  ViewData ── translate ──┐   │
 └──────────────────────────┼───┘         └──────────────────────────┼───┘
                            │ CFFI typed API     same C API           │
                  ┌─────────▼──────────────────────▼────────┐
                  │ libubo_lvgl (this directory)             │
                  │  view-model API → LVGL widget tree       │
                  │  backend: SDL | buffer | ST7789 SPI      │
                  └──────────────────────────────────────────┘
```

In **phase 1** a Python process owns the transport and calls the C API over CFFI.
In **phase 2** the C client (`client/`) owns the transport itself — it speaks
**gRPC-Web over HTTP/1.1** (web-grpc only, via Envoy), decodes protobuf with
**nanopb**, and calls the *same* C API. It runs on macOS today (SDL backend) and
on the **ESP32-C6-Touch-AMOLED-1.8** under ESP-IDF (libcurl→`esp_http_client`,
pthreads→FreeRTOS tasks, SH8601 368×448 QSPI AMOLED backend, FT3168 touch) — see
[`esp32/README.md`](esp32/README.md). The framing codec and nanopb are MCU-ready
and reused verbatim. The Python bridge stays for the native gRPC/HTTP-2 path.

## Directory layout

```
ubo_lvgl/
  CMakeLists.txt
  lv_conf.h                 # LVGL configuration (RGB565, SDL, fonts, FS driver)
  lvgl/                     # LVGL v9.3 (git submodule)
  include/ubo_lvgl.h        # PUBLIC C API — the stable seam
  assets/
    fonts/ArimoNerdFont-Regular.ttf   # source for the icon font
    ubo_icons_{18,14}.bin             # runtime icon fonts (full Nerd-Font range)
  src/
    ubo_lvgl.c              # init, LVGL loop, lock, render entry points, snapshot
    sim_main.c              # ubo_lvgl_sim   — desktop SDL window
    snapshot_main.c         # ubo_lvgl_snapshot — headless BMP of a sample view
    display/                # backend_sdl.c | backend_buffer.c | backend_st7789.c
    fonts/                  # generated LVGL fonts + runtime loader (fonts/README.md)
    views/                  # screen chrome, item bar, page slider, per-view builders
  client/                   # native C web-grpc client (ubo_lvgl_client)
    proto/ubo_client.proto  # curated, wire-compatible subset of the core proto
    proto/ubo_client.pb.*   # committed nanopb output (regen with proto/regen.sh)
    grpc_web_frame.{c,h}    # gRPC-Web framing codec (MCU-portable, unit-tested)
    http_transport.{c,h}    # HTTP/1.1 transport (libcurl; esp_http_client later)
    ubo_rpc.{c,h}           # dispatch + subscribe_store/_event over frame+nanopb
    view_translate.{c,h}    # decoded ViewData → ubo_lvgl_render_* (markup/colors)
    keymap.{c,h}            # key name → KeypadKey*/AudioToggle action
    client_main.c           # threads, reconnect, input queue, arg/env parsing
  third_party/nanopb/       # nanopb runtime + generator (git submodule)
```

## Prerequisites

- A C toolchain + CMake ≥ 3.15
- **SDL2** (desktop backend): `brew install sdl2` (macOS) / `apt install libsdl2-dev`
- **libcurl** (native C client): ships with macOS / `apt install libcurl4-openssl-dev`
- The submodules (LVGL renderer + nanopb for the C client):
  ```sh
  git submodule update --init ubo_lvgl/lvgl ubo_lvgl/third_party/nanopb
  ```

## Build (C library + tools)

```sh
cmake -S ubo_lvgl -B ubo_lvgl/build -DCMAKE_PREFIX_PATH=/opt/homebrew   # macOS/brew
cmake --build ubo_lvgl/build -j8
```

Targets produced in `ubo_lvgl/build/`:

| Target | What it is |
|--------|------------|
| `libubo_lvgl.{dylib,so}` | the renderer library (loaded by the Python bridge) |
| `ubo_lvgl_sim` | standalone SDL window showing the current screen |
| `ubo_lvgl_snapshot` | renders a sample view to a BMP with no display (CI) |
| `client/ubo_lvgl_client` | native C web-grpc client (transport + render) |
| `client/ubo_client_test_{frame,decode}` | unit tests (run via `ctest`) |

CMake options: `-DUBO_WITH_SDL=ON|OFF` (default ON), `-DUBO_WITH_ST7789=ON|OFF`
(default OFF; Raspberry Pi), `-DUBO_WITH_CLIENT=ON|OFF` (default ON; the native C
client). The offscreen buffer backend is always built. Run the C unit tests with
`ctest --test-dir ubo_lvgl/build`.

## Run (desktop, against a live core)

1. Start the core's gRPC server (no GUI of its own):
   ```sh
   uv run ubo-core            # serves 127.0.0.1:50051
   ```
2. Run the client (uv creates/syncs its venv on first run):
   ```sh
   uv run --directory ubo_app/lvgl_gui python -m ubo_lvgl_gui_client --backend sdl
   ```
   An SDL window opens and mirrors what the core renders. Keys (desktop):
   `↑/k` up, `↓/j` down, `1/2/3` → L1/L2/L3, `←/esc/h` back, `backspace` home.

The bridge auto-locates `libubo_lvgl` under `ubo_lvgl/build/` and the icon fonts
under `ubo_lvgl/assets/` (override with `UBO_LVGL_LIB` / `UBO_LVGL_ASSETS_DIR`).

### Run the native C client (no Python)

The C client needs the core reachable through an **Envoy** proxy that exposes the
`/grpc` web-grpc endpoint (the same one the web-UI uses; default port `50052`).
With core + Envoy running:

```sh
UBO_LVGL_ASSETS_DIR=ubo_lvgl/assets \
  ubo_lvgl/build/client/ubo_lvgl_client --backend sdl \
  --web-grpc-url http://localhost:50052/grpc
```

Config (flags or env): `--backend {sdl,st7789,buffer}`, `--host HOST`,
`--web-grpc-url URL` / `UBO_LVGL_GUI_WEB_GRPC_URL` (defaults to
`http://<host>:50052/grpc`). Same desktop keys as the Python client. The protobuf
bindings are committed; regenerate after changing `client/proto/ubo_client.proto`
with `client/proto/regen.sh` (needs `uv` + python `protobuf`).

### Transports (native gRPC vs gRPC-Web)

The client can reach the core over two wire transports. Both carry the identical
protobuf messages — only the framing/HTTP layer differs — so behaviour is the
same either way:

| Transport | Protocol | Talks to | Default endpoint |
| --------- | -------- | -------- | ---------------- |
| `grpc` (default) | native gRPC over HTTP/2 | the core's gRPC port directly | `--host`:`--port` (`localhost:50051`) |
| `web-grpc` | gRPC-Web over HTTP/1.1 | an **Envoy** proxy's `/grpc` endpoint (same one the web-UI uses) | `http://<host>:50052/grpc` |

`web-grpc` exists for resource-constrained targets (eventually an ESP32 in C)
where a full HTTP/2 gRPC stack is impractical but an HTTP client is trivial.

Select it with a CLI flag or an environment variable (the flag wins; the env var
is the fallback / default):

```sh
# Native gRPC (default — nothing extra needed)
python -m ubo_lvgl_gui_client --backend sdl --host localhost --port 50051

# gRPC-Web via Envoy, CLI flags
python -m ubo_lvgl_gui_client --backend sdl \
  --transport web-grpc --web-grpc-url http://localhost:50052/grpc

# gRPC-Web via Envoy, environment variables
UBO_LVGL_GUI_TRANSPORT=web-grpc \
UBO_LVGL_GUI_WEB_GRPC_URL=http://localhost:50052/grpc \
  python -m ubo_lvgl_gui_client --backend sdl
```

| Setting | CLI flag | Env var | Default |
| ------- | -------- | ------- | ------- |
| Transport | `--transport {grpc,web-grpc}` | `UBO_LVGL_GUI_TRANSPORT` | `grpc` |
| Envoy URL (web-grpc only) | `--web-grpc-url URL` | `UBO_LVGL_GUI_WEB_GRPC_URL` | `http://<host>:50052/grpc` |

For `web-grpc`, an Envoy proxy exposing `/grpc` must be reachable — on an Ubo
device this is the same Envoy the web-UI service brings up (listening on
`50052` by default). The `--host`/`--port` flags still apply to the `grpc`
transport.

### Selecting the backend via the supervisor

The normal `ubo` command (the supervisor in `ubo_app/main.py`) picks the GUI
client from an env var, so the same command / service drives either renderer:

```sh
UBO_GUI_BACKEND=lvgl  UBO_LVGL_BACKEND=st7789  ubo   # LVGL on the ST7789 panel
UBO_GUI_BACKEND=kivy  ubo                            # Kivy (default)
```

`UBO_GUI_BACKEND` is `kivy` by default; set it to `lvgl` to spawn
`ubo-lvgl-gui-client` with `--backend $UBO_LVGL_BACKEND` (`st7789` on a device,
`sdl` on desktop). In a systemd unit, set `Environment=UBO_GUI_BACKEND=lvgl`.
(The Kivy client uses lgpio, which needs a writable working directory.)

### Headless snapshots (no display)

The C library can render to an offscreen RGB565 framebuffer, used for CI snapshot
tests and screenshots when there is no window:

```sh
ubo_lvgl/build/ubo_lvgl_snapshot out.bmp menu      # or: home
```

From Python (drives the real render path via the bridge):

```python
from ubo_lvgl_gui_client.bridge import Renderer, BACKEND_BUFFER, MenuView, MenuItem
r = Renderer(); r.init(BACKEND_BUFFER, 240, 240)
r.render_menu(MenuView(title='Main', items=[MenuItem(label='WiFi')]))
r.snapshot('/tmp/out.bmp')
```

### gRPC screenshot facility

When connected to a core, the client answers the core's `ScreenshotEvent`
(e.g. the `HOME`+`L1` keypad shortcut, or a dispatched `TakeScreenshotAction`) by
encoding its framebuffer to PNG and returning a `ScreenshotDataAction`. The core
saves it under `screenshots/ubo-screenshot-NNN.png` — the same mechanism the Kivy
client uses, enabling apple-to-apple comparison and CI window-snapshot tests.

## How it works

**View model.** `include/ubo_lvgl.h` declares one struct per view
(`ubo_home_view`, `ubo_menu_view`, …) mirroring the core's `ViewData`, plus
`ubo_status_bar`. The render entry points (`ubo_lvgl_render_menu(...)`, …) rebuild
the LVGL widget tree for that view.

**Threading.** LVGL runs its own loop (`ubo_lvgl_run`). A single mutex
(`ubo_lock`/`ubo_unlock`) serializes all LVGL access, so the render functions can
be called from another thread (the Python gRPC loop in phase 1). Strings passed
in are only read during the call. On macOS the SDL window must be driven from the
main thread, so the launcher runs the LVGL loop on the main thread and gRPC on a
worker.

**Layout (matches ubo_gui).** The content area is full-screen with the
header/footer drawn as overlays on top. Views lay out in the middle **band**
(between a 34 px header and a 36 px footer) so the centre item is always
screen-centred. Menu items are right-rounded "D" bars (52 px tall, 7 px gap).
Paginated menus show the **header only on the first page** and the **footer only
on the last page**; middle pages reveal the previous/next items peeking into the
header/footer space (ubo_gui's `render_surroundings`). A thin page-position
slider tracks the current page, and view changes animate with a directional
slide.

**Fonts.** Text uses built-in Montserrat. Icons use a Nerd Font (the same
`ArimoNerdFont` ubo_gui registers) generated to `assets/ubo_icons_*.bin` and
loaded at runtime via LVGL's filesystem driver; a small compiled subset is the
fallback. See `src/fonts/README.md` to regenerate / add glyphs.

**Backends.** `display/backend_sdl.c` (desktop window + key events),
`display/backend_buffer.c` (offscreen RGB565 for snapshots),
`display/backend_st7789.c` (Raspberry Pi SPI panel — Step 6, WIP).

## Verifying changes

- C: build with `-Wall -Wextra` (clean), then snapshot a view and eyeball it.
- Python: `uv run poe typecheck:lvgl-gui && uv run poe lint:lvgl-gui` (from the repo root)
- End-to-end: run a core + the SDL client and compare to the Kivy client.

## Status / roadmap

**Phase 1** (Python bridge) is complete and verified on desktop and on the
physical ST7789 panel (all core navigation views, keypad input, transitions,
icons, status bar, generic `RenderViewData` widgets, snapshot facility).

**Phase 2** (native C client, `client/`) runs on macOS against a live core +
Envoy: web-grpc transport, nanopb decode, full view translation, input dispatch,
and stream reconnect are verified.

**ESP32-C6 port** (`esp32/`) runs the same renderer + client on the Waveshare
ESP32-C6-Touch-AMOLED-1.8 (SH8601 368×448 QSPI AMOLED, FT3168 touch, WiFi 6):
responsive layout, `esp_http_client` web-grpc transport, live store/event
streams, touch navigation + interactive volume, reconnect/backoff with a
disconnect overlay, and **on-device WiFi setup** via a captive portal (join the
`ubo-setup` AP from a phone, pick your network + optional ubo-core host/port; hold
BOOT ~3s to re-provision) — all verified on-device. See the WiFi setup journey and
build steps in [`esp32/README.md`](esp32/README.md). The camera viewfinder is
deferred on-device (512KB SRAM, no PSRAM).

Remaining:

- **gRPC screenshot round-trip** in C (PNG + sha256) — deferred; rendering is
  verified via the BUFFER backend + `ubo_lvgl_snapshot()` instead.
- **frame_stream** is currently always-subscribed + filtered by active stream id;
  a dynamic (un)subscribe (bandwidth) is a follow-up for the MCU.
- **camera viewfinder on-device** — needs a downscaling/streaming-decode strategy
  to fit under 512KB SRAM.
