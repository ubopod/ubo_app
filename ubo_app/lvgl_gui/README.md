# ubo-lvgl-gui-client

Python launcher and gRPC bridge for the LVGL (C) GUI renderer. It connects to the
ubo-core gRPC server, translates `ViewData`/`StatusBarData` into calls on the C
renderer (`libubo_lvgl`) via CFFI, forwards keypad input, and answers screenshot
requests.

Run (from the repo root):

```sh
uv run ubo-core   # serves 127.0.0.1:50051
uv run --directory ubo_app/lvgl_gui python -m ubo_lvgl_gui_client --backend sdl
```

Modules: `bridge.py` (CFFI ↔ C structs), `client.py` (gRPC subscribe/reconnect),
`view_translator.py` (betterproto → bridge), `keyboard.py`, `screenshot.py`,
`__main__.py`.

## Transports

The client can reach ubo-core over two wire transports, selected at launch:

- **`grpc`** (default) — native gRPC over HTTP/2 (`UboRPCClient`, grpclib),
  connecting directly to the core's gRPC port (`--host`/`--port`).
- **`web-grpc`** — gRPC-Web over HTTP/1.1 through an **Envoy** proxy (the same
  `/grpc` endpoint the web-UI uses, default Envoy port `50052`). Intended for
  resource-constrained targets where an HTTP/2 gRPC stack is impractical.

Select via flags or environment variables:

```sh
# native gRPC (default)
python -m ubo_lvgl_gui_client --transport grpc --host ubo-r.local --port 50051

# gRPC-Web via Envoy
UBO_LVGL_GUI_TRANSPORT=web-grpc \
UBO_LVGL_GUI_WEB_GRPC_URL=http://ubo-r.local:50052/grpc \
  python -m ubo_lvgl_gui_client
```

Only the wire layer differs — request/response bodies are the identical protobuf
messages, so the betterproto bindings are reused for both. `grpc_web_frame.py`
holds the dependency-free framing codec and is the **portability boundary** for
the eventual ESP32 (C) port: that module maps 1:1 to a C buffer-and-drain loop
(swap betterproto for nanopb and httpx for `esp_http_client`).

See **`ubo_lvgl/README.md`** at the repo root for the full architecture, build,
and run guide (the C renderer is the main component).
