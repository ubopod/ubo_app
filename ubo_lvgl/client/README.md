# ubo_lvgl_client — native C web-grpc client

A pure-C client that drives `libubo_lvgl` directly: it speaks **gRPC-Web over
HTTP/1.1** to ubo-core's Envoy proxy, decodes protobuf with **nanopb**, and calls
the `ubo_lvgl_*` render API. It replaces the Python bridge for the web-grpc path
and is the basis for the ESP32-C6 (ESP-IDF) port. The native gRPC/HTTP-2 path
stays Python-only.

## Layout

| File | Role |
|------|------|
| `proto/ubo_client.proto` | curated, **wire-compatible** subset of the core proto (field numbers match; names may differ to dodge C keywords). Keeps nanopb output tiny — the real `Action` (~253 members) / `Event` (~133) oneofs are trimmed to the few the client uses. |
| `proto/ubo_client.pb.{c,h}` | committed nanopb output (pointer/malloc mode). Regenerate with `proto/regen.sh`. |
| `grpc_web_frame.{c,h}` | gRPC-Web framing: `[1B flag][4B BE len][payload]`, flag `0x80` = trailer. Incremental parser for chunk-split streams. **Dependency-free, unit-tested, the cleanest C↔MCU unit.** |
| `http_transport.{c,h}` | thin HTTP interface: one unary POST, one streaming POST. **libcurl** backend today; an `esp_http_client` backend implements the same two calls on ESP-IDF. |
| `ubo_rpc.{c,h}` | composes frame + http + nanopb into `DispatchAction` / `SubscribeStore` / `SubscribeEvent`. |
| `view_translate.{c,h}` | decoded `ViewData`/`StatusBarData` → `ubo_lvgl_render_*` (Kivy-markup stripping, color mapping, double-wrapped item unwrap, notification slots). Port of `view_translator.py`. |
| `keymap.{c,h}` | key name → `KeypadKey*` / `AudioToggleMuteStatus` action. |
| `client_main.c` | threads, reconnect/backoff, input queue, arg/env parsing. |

## Wire notes

- `current_view` arrives as a `google.protobuf.Any` whose `value` is the
  **concrete** view message (`HomeViewData`, …) identified by `Any.type_url` —
  not a `ViewData` oneof. The client dispatches on the type_url suffix.
- `SubscribeStore([current_view, status_bar, is_blanked])` results are decoded
  **positionally**; `is_blanked` is a `BoolValue`, `None` is `Empty`.
- A non-200 from Envoy (e.g. 503 when core is down) is surfaced as a transport
  error so the reconnect loop engages.

## Threading

`client_main.c` runs LVGL on the main thread (`ubo_lvgl_run(false)`), plus a
store-stream thread (owns the disconnect overlay + reconnect), an event-stream
thread (`app_scroll` + `menu_choose` + `frame_stream`), and a dispatch worker
that drains the key queue so input never blocks on the network.

## ESP-IDF port (next)

The seams designed for it: implement `http_transport.h` over `esp_http_client`;
map the three worker threads to FreeRTOS tasks; add an AMOLED/QSPI display
backend under `../src/display/`. `grpc_web_frame.*` and the nanopb schema compile
as-is; nanopb has an official ESP-IDF component.

## Tests

`ctest --test-dir ../build` runs `frame_codec` (framing) and `decode_home`
(curated schema vs a captured server blob). Live harnesses (need core + Envoy):
`ubo_client_probe` (dispatch/subscribe round-trip) and
`ubo_client_render_snapshot` (renders live views to BMP for parity vs Python).
