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
In **phase 2** the C client (`client/`) owns the transport itself, decodes
protobuf with **nanopb**, and calls the *same* C API. It speaks one of two wire
transports, selected at build time (see [Transports](#c-client-transport-tcp-lite-default-vs-grpc-web)
below): **tcp-lite** (default — a lightweight raw-TCP protocol, no HTTP/Envoy)
or **gRPC-Web over HTTP/1.1** (via Envoy). It runs on macOS today (SDL backend)
and on the **ESP32-C6-Touch-AMOLED-1.8** under ESP-IDF (pthreads→FreeRTOS tasks,
SH8601 368×448 QSPI AMOLED backend, FT3168 touch) — see
[`esp32/README.md`](esp32/README.md). Both framing codecs and nanopb are
MCU-ready and reused verbatim. The Python bridge stays for the native
gRPC/HTTP-2 path.

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
  client/                   # native C client (ubo_lvgl_client)
    proto/ubo_client.proto  # curated, wire-compatible subset of the core proto
    proto/ubo_client.pb.*   # committed nanopb output (regen with proto/regen.sh)
    tcp_lite_frame.{c,h}    # tcp-lite framing codec (MCU-portable, unit-tested)
    tcp_lite_transport.{c,h}# raw-TCP socket transport (one file, desktop+ESP32)
    ubo_rpc_tcp_lite.c      # tcp-lite RPC layer — same contract as ubo_rpc.h
    grpc_web_frame.{c,h}    # gRPC-Web framing codec (MCU-portable, unit-tested)
    http_transport.{c,h}    # HTTP/1.1 transport (libcurl; esp_http_client on ESP32)
    ubo_rpc.{c,h}           # gRPC-Web RPC layer: dispatch + subscribe over frame+nanopb
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
| `client/ubo_lvgl_client` | native C client (transport + render) |
| `client/ubo_client_test_{frame,tcp_lite_frame,decode,chunk}` | unit tests (run via `ctest`) |

CMake options: `-DUBO_WITH_SDL=ON|OFF` (default ON), `-DUBO_WITH_ST7789=ON|OFF`
(default OFF; Raspberry Pi), `-DUBO_WITH_CLIENT=ON|OFF` (default ON; the native C
client), `-DUBO_TRANSPORT=tcp_lite|grpc_web` (default `tcp_lite`; see
[Transports](#c-client-transport-tcp-lite-default-vs-grpc-web) below). The
offscreen buffer backend is always built; both framing codecs (tcp-lite and
gRPC-Web) are always compiled regardless of `UBO_TRANSPORT`, so `ctest` always
exercises both. Run the C unit tests with `ctest --test-dir ubo_lvgl/build`.

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

By default the C client is built with the **tcp-lite** transport (see below) and
talks directly to the core's `mcu_server.py` listener (default port `50054`, no
Envoy needed). With the core running:

```sh
UBO_LVGL_ASSETS_DIR=ubo_lvgl/assets \
  ubo_lvgl/build/client/ubo_lvgl_client --backend sdl \
  --web-grpc-url localhost:50054
```

If built with `-DUBO_TRANSPORT=grpc_web`, the client instead needs the core
reachable through an **Envoy** proxy that exposes the `/grpc` web-grpc endpoint
(the same one the web-UI uses; default port `50052`):

```sh
UBO_LVGL_ASSETS_DIR=ubo_lvgl/assets \
  ubo_lvgl/build/client/ubo_lvgl_client --backend sdl \
  --web-grpc-url http://localhost:50052/grpc
```

Config (flags or env): `--backend {sdl,st7789,buffer}`, `--host HOST`,
`--web-grpc-url URL` / `UBO_LVGL_GUI_WEB_GRPC_URL` — a bare `host:port` for
tcp-lite, a full URL for gRPC-Web (defaults to `http://<host>:50052/grpc` when
built for gRPC-Web). Same desktop keys as the Python client. The protobuf
bindings are committed; regenerate after changing `client/proto/ubo_client.proto`
with `client/proto/regen.sh` (needs `uv` + python `protobuf`).

### C client transport: tcp-lite (default) vs gRPC-Web

The native C client speaks one of two wire transports to the core, selected at
**build time** — behavior is otherwise identical (same nanopb messages, same
`ubo_rpc.h` API, same reconnect/backoff on the caller side):

| Transport | CMake flag | Wire format | Talks to | Default port |
| --------- | ---------- | ----------- | -------- | ------------- |
| `tcp_lite` (**default**) | `-DUBO_TRANSPORT=tcp_lite` | `[1B message_type][varint length][protobuf payload]` over a raw TCP socket | `ubo_app/rpc/mcu_server.py` directly — no HTTP, no Envoy | `50054` |
| `grpc_web` | `-DUBO_TRANSPORT=grpc_web` | gRPC-Web framing (`[1B flag][4B length][payload]`) over HTTP/1.1 | an **Envoy** proxy's `/grpc` endpoint | `50052` |

```sh
cmake -S ubo_lvgl -B ubo_lvgl/build                          # tcp_lite (default)
cmake -S ubo_lvgl -B ubo_lvgl/build -DUBO_TRANSPORT=grpc_web  # opt back into gRPC-Web
```

**Why tcp-lite exists.** Modeled on [ESPHome's native
API](https://developers.esphome.io/architecture/api/): a bare TCP socket is
enough for a link that only ever needs to carry 3 RPCs
(`DispatchAction`/`SubscribeStore`/`SubscribeEvent` — never `SecretsService`) to
one trusted peer. Dropping HTTP/1.1 (headers, chunked transfer,
libcurl/`esp_http_client`) meaningfully shrinks ESP32 firmware size and
complexity versus gRPC-Web/Envoy, without changing the payload bytes at all —
nanopb encode/decode is identical either way.

**Framing.** `tcp_lite_frame.{c,h}` is a direct structural sibling of
`grpc_web_frame.{c,h}` — same incremental-parser contract (`_feed()`/`_next()`,
poison-on-bad-input), but with a *varint* length instead of a fixed 4-byte one,
since there's no HTTP layer to carry the length for it. `message_type` is a
hand-defined 1-byte discriminant (not derived from the core's proto oneofs —
there's no RPC-selector tag there to reuse):

| Constant | Value |
| -------- | ----- |
| `DISPATCH_ACTION_REQUEST` / `_RESPONSE` | `0x01` / `0x02` |
| `SUBSCRIBE_STORE_REQUEST` / `_RESPONSE` | `0x03` / `0x04` |
| `SUBSCRIBE_EVENT_REQUEST` / `_RESPONSE` | `0x05` / `0x06` |
| `ERROR` (reserved) | `0x7E` |
| `PING` (reserved, future keepalive) | `0x7F` |

Max frame size `1<<20` (matches gRPC-Web's cap). These constants are duplicated
by hand in `ubo_app/rpc/mcu_server.py` (Python) — there is no shared source of
truth or generator, so the two files must be kept in sync manually if a message
type is ever added or renumbered (see `.claude/skills/lvgl-maintenance/SKILL.md`).

**Transport + RPC layer.** `tcp_lite_transport.{c,h}` is one file shared by
desktop *and* ESP32 (plain BSD sockets work on both — no libcurl/
`esp_http_client` split needed here, unlike the gRPC-Web transport).
`ubo_rpc_tcp_lite.c` implements the exact same public contract as `ubo_rpc.h`
that `ubo_rpc.c` (gRPC-Web) does, so `client_main.c`/`client_app.c`/
`view_translate.c` etc. never know which transport is compiled in.
`DispatchAction` opens a fresh connection per call (preserves today's
self-healing property — the dispatch thread/task has no reconnect logic of its
own); `SubscribeStore`/`SubscribeEvent` connect once and stream for the life of
the subscription, same as the gRPC-Web path.

**Server side.** `ubo_app/rpc/mcu_server.py` is a small `asyncio` TCP listener,
parallel to (not replacing) the native gRPC server in `ubo_app/rpc/server.py`.
It calls directly into the same `StoreService` methods gRPC uses — one
business-logic implementation, two thin transport adapters. It binds
`0.0.0.0:50054` by default (`UBO_MCU_LISTEN_ADDRESS`/`UBO_MCU_LISTEN_PORT`),
**plaintext and unauthenticated** — a deliberate phase-1 decision, no
Noise/TLS-equivalent yet.

**ESP32.** Both link types are supported: `UBO_CORE_MCU_ADDR` (WiFi,
menuconfig-baked `host:port`, no NVS override yet) and `UBO_USB_CORE_MCU_ADDR`
(USB-PPP, defaults to `10.66.0.1:50054` — same PPP-peer host
`UBO_USB_CORE_GRPC_WEB_URL` uses, different port). tcp-lite works over WiFi or
USB-PPP the same way gRPC-Web did — no transport-specific link limitation. See
[`esp32/README.md`](esp32/README.md) and `.claude/skills/lvgl-run/SKILL.md` for
the full ESP-IDF build recipe.

**Resource footprint (ESP32-C6, measured via `idf.py size`/`size-components`
on matching PPP-profile firmware, transport as the only variable):**

| | tcp-lite | gRPC-Web | Saved |
| --- | --- | --- | --- |
| Total flash image | 2,033,106 B (1,986 KB) | 2,125,084 B (2,075 KB) | **91,978 B (≈ 89.8 KB, ~4.3%)** |
| Static RAM (`.bss`/`.data`) | 190,810 B | 190,890 B | 80 B (negligible) |

The flash savings come entirely from components tcp-lite never links, since
it never touches `esp_http_client`:

| Component | Bytes (gRPC-Web only) |
| --- | --- |
| `libmbedtls.a` (beyond the 32 B WPA2 baseline both builds need) | 26,788 |
| `libesp_http_client.a` | 9,766 |
| `libmbedx509.a` (X.509 parsing — pulled in even for plain HTTP, not HTTPS) | 8,245 |
| `libesp-tls.a` | 7,062 |
| `libtcp_transport.a` (ESP-IDF's generic transport abstraction) | 4,282 |
| **Itemized subtotal** | **56,143 (54.8 KB)** |

The remaining ~36 KB of the delta is spread across marginal increases in
components already present in both builds (more of libc, lwip socket
helpers, etc. actually referenced by the HTTP code path) rather than
concentrated in one library. `libubo_client_core.a` itself is essentially
transport-symmetric (23,486 B gRPC-Web vs 23,534 B tcp-lite) — the savings
are entirely about what tcp-lite *avoids* linking, not the tcp-lite code
itself being smaller.

Not (yet) measured, but expected to matter more in practice than the static
numbers above:
- **Per-request heap.** `esp_http_client`'s per-connection handle carries
  header-parsing and chunked-transfer state; tcp-lite's equivalent is just
  `struct ubo_tcp_lite { int fd; uint8_t rbuf[2048]; }` — smaller and fully
  deterministic. No live heap-diff has been captured to put a number on this.
- **Per-message wire overhead.** gRPC-Web pays an HTTP/1.1 request-line +
  headers (~150–250 B) plus its own 5-byte frame header per message, plus
  chunked-transfer-encoding overhead on streamed responses. tcp-lite's entire
  frame header is 2–6 B (`[1B type][1–5B varint length]`). For something like
  a keypress dispatch (a handful of protobuf bytes), HTTP overhead alone can
  exceed the payload several times over; tcp-lite's overhead is close to
  zero.
- **Task stack sizes are unchanged** — `store_task`/`event_task`/
  `dispatch_task` (8192/6144/4096 B) are identical either way.

### Python bridge transports (native gRPC vs gRPC-Web)

Separately from the C client's tcp-lite/gRPC-Web choice above, the **Python**
bridge (`ubo_lvgl_gui_client`) can reach the core over two wire transports of
its own. Both carry the identical protobuf messages — only the framing/HTTP
layer differs — so behaviour is the same either way:

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

Reading the framebuffer requires the offscreen buffer backend, so run the Python
client headless to enable screenshot-based testing (no window opens; everything
else behaves the same):

```sh
uv run --directory ubo_app/lvgl_gui python -m ubo_lvgl_gui_client --backend buffer
```

Note the LVGL framebuffer is RGB565 (PNG-encoded as RGB888) while the Kivy
client captures RGBA, so the two clients' screenshot hashes are compared
against their own baselines — parity is visual, not byte-identical.

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

**Phase 2** (native C client, `client/`) runs on macOS against a live core, on
both wire transports: nanopb decode, full view translation, input dispatch,
and stream reconnect are verified for gRPC-Web (via Envoy) and for **tcp-lite**
(direct to `mcu_server.py`, now the default).

**ESP32-C6 port** (`esp32/`) runs the same renderer + client on the Waveshare
ESP32-C6-Touch-AMOLED-1.8 (SH8601 368×448 QSPI AMOLED, FT3168 touch, WiFi 6):
responsive layout, live store/event streams, touch navigation + interactive
volume, reconnect/backoff with a disconnect overlay, and **on-device WiFi
setup** via a captive portal (join the `ubo-setup` AP from a phone, pick your
network + optional ubo-core host/port; hold BOOT ~3s to re-provision) — all
verified on-device. Transport/link coverage: gRPC-Web is verified on-device
over both WiFi and USB-PPP (pre-existing); tcp-lite (now the default) is
verified live on-device over **WiFi**, and builds correctly for **USB-PPP**
(`UBO_USB_CORE_MCU_ADDR` picked up, compile-time guard confirmed working) but
is not yet live-verified over that link. See the WiFi setup journey and build
steps in [`esp32/README.md`](esp32/README.md). The camera viewfinder is
deferred on-device (512KB SRAM, no PSRAM).

Remaining:

- **gRPC screenshot round-trip** in C (PNG + sha256) — deferred; rendering is
  verified via the BUFFER backend + `ubo_lvgl_snapshot()` instead.
- **frame_stream** is currently always-subscribed + filtered by active stream id;
  a dynamic (un)subscribe (bandwidth) is a follow-up for the MCU.
- **camera viewfinder on-device** — needs a downscaling/streaming-decode strategy
  to fit under 512KB SRAM.
- **tcp-lite auth/encryption** — phase 1 is deliberately plaintext/
  unauthenticated (`mcu_server.py` binds `0.0.0.0:50054` with no gate); a
  Noise-protocol-style handshake is a follow-up before wider exposure.
- **tcp-lite NVS provisioning** — the WiFi captive portal only provisions the
  gRPC-Web endpoint today; `UBO_CORE_MCU_ADDR` is menuconfig-baked only.
