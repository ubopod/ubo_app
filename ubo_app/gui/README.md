# ubo-gui-client

The Kivy GUI client for ubo-app. It is a **thin renderer**: it holds no
application state and contains no business logic. It connects to the headless
core over gRPC, subscribes to the computed view stream, draws it, and dispatches
the user's input back as actions.

It is the reference implementation of the client contract — its C/LVGL sibling
([`ubo_lvgl/`](../../ubo_lvgl/README.md)) and the TUI
([`ubo_app/tui/`](../tui/README.md)) render the same stream.

## Running

```sh
uv run ubo-core                      # the headless core, serves 127.0.0.1:50051
uv run --directory ubo_app/gui ubo-gui-client
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `--host` | gRPC server host | `localhost` |
| `--port` | gRPC server port | `50051` |
| `-v` / `--verbose` | DEBUG logging | off |

It installs into **its own virtualenv**, separate from the core's — it depends
on `headless-kivy` and `ubo-gui`, which the headless core deliberately does not.
OTA updates and `poe device:deploy` install it as a separate wheel. Type-check
it with `uv run poe typecheck:gui`, which targets that venv.

## What it renders

The core sends serializable `ViewData`; nothing callable or Kivy-shaped crosses
the wire. `view_renderer.py` turns each view into widgets:

| Area | Modules |
| --- | --- |
| App shell & lifecycle | `app.py`, `__main__.py`, `splash.py`, `display.py` |
| gRPC transport | `client.py` |
| View dispatch | `view_renderer.py` |
| Menu chrome | `menu_central.py`, `menu_header.py`, `menu_footer.py`, `menu_notification_handler.py` |
| Input | `keyboard.py` |
| Device | `eeprom.py`, `constants.py`, `gui_utils.py` |

`widgets/` holds the generic render widgets, registered by kind in
`GENERIC_RENDER_WIDGETS`: `qr_code`, `qr_code_carousel`, `readings`, `status`,
`text_viewer`, `image_viewer`, `frame_stream` — plus `chat`, `home_page`,
`notification_info` and the `video_viewer`.

## Two rules that bite

- **The application registry is local.** The core's store holds an
  `ApplicationStackItem(application_id=...)`, never a widget class. Full-screen
  pages must be registered *twice*: with `register_application(...)` in
  `ubo_app/store/ubo_actions.py` on the core side, and again in this process's
  own registry (`pages/__init__.py`), which exists precisely because the core's
  registry is not importable from this venv.
- **Kivy work belongs on the main thread.** gRPC callbacks arrive on other
  threads; anything touching widgets has to hop back via `@mainthread`.

See [`.claude/rules/coding-style.md`](../../.claude/rules/coding-style.md) for
the serializable-state rules this client depends on, and
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../docs/architecture/UI_REDUX_ARCHITECTURE.md)
for the store/view model.
