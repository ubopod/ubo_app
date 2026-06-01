# ubo-lvgl-gui-client

Python launcher and gRPC bridge for the LVGL (C) GUI renderer. It connects to the
ubo-core gRPC server, translates `ViewData`/`StatusBarData` into calls on the C
renderer (`libubo_lvgl`) via CFFI, forwards keypad input, and answers screenshot
requests.

Run (from the repo root):

```sh
uv run ubo-core   # serves 127.0.0.1:50051
PYTHONPATH=ubo_app/gui:ubo_app/rpc \
  ubo_app/gui/ubo_lvgl_gui_client/.venv/bin/python -m ubo_lvgl_gui_client --backend sdl
```

Modules: `bridge.py` (CFFI ↔ C structs), `client.py` (gRPC subscribe/reconnect),
`view_translator.py` (betterproto → bridge), `keyboard.py`, `screenshot.py`,
`__main__.py`.

See **`ubo_lvgl/README.md`** at the repo root for the full architecture, build,
and run guide (the C renderer is the main component).
