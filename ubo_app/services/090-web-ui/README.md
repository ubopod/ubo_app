# Web UI Service (`090-web-ui`)

## Overview

The web-ui service runs an on-device **web dashboard**: a Quart (async Flask-style) HTTP server that
serves a compiled React/TypeScript single-page app plus a set of JSON/form endpoints. Its primary
job is to render the current store state to a browser and to accept **input** from that browser —
the "web dashboard" input method behind Wi-Fi setup, voice-command forms, file uploads, etc. — so a
user can drive the device without the physical keypad. It also brings up a captive Wi-Fi hotspot
(via the wifi service) when the device is offline so a phone can reach the dashboard for onboarding.

It loads in the `090-` tier (app-like services) because it consumes many other slices (wifi, docker,
notifications, input) and only makes sense once the store and those services exist.

> Architecture background (store, dumb-client, gRPC, action/event flow) lives in
> [`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).
> This README covers only what is specific to this service.

## Files

| Path                       | Purpose                                                                    |
| -------------------------- | -------------------------------------------------------------------------- |
| `ubo_handle.py`            | Registration; async `setup` registers the reducer then `await init_service()`. |
| `setup.py`                 | Runtime: the Quart server, its routes, hotspot bootstrap, input plumbing.  |
| `reducer.py`              | Pure reducer for the `web_ui` slice — tracks active web input descriptions. |
| `templates/index.jinja2`   | The single Jinja2 template: bootstraps `WEB_UI_CONFIG` + serialized state, loads `main.js`. |
| `web-app/`                 | The TypeScript/React frontend project (see below).                        |
| `web-app/package.json`     | Frontend deps + scripts (`proto:compile`, `build`, `lint`).                |
| `web-app/webpack.config.mjs` | Webpack build → `web-app/dist/main.js` (ES module) served as a static file. |
| `web-app/src/client.tsx`   | Frontend entry point (`init(state)`), theme, gRPC-web client wiring.       |
| `web-app/src/components/`  | React views (AppShell, ApplicationView, ChatView, PromptView, Status, …). |
| `web-app/src/store/`       | Frontend store/state-manager, action dispatcher, audio input.             |
| `web-app/src/display/`, `inputs.tsx`, `main-view.tsx` | Rendering + input-form components.              |
| `web-app/src/bindings/`    | Generated gRPC-web bindings (gitignored; produced by `proto:compile`).     |

Store types: [`ubo_app/store/services/web_ui.py`](../../store/services/web_ui.py).

## State

Slice: `state.web_ui` — [`WebUIState`](../../store/services/web_ui.py):

| Field           | Type                              | Meaning                                                     |
| --------------- | --------------------------------- | ---------------------------------------------------------- |
| `active_inputs` | `list[WebUIInputDescription]`     | The input forms currently awaiting a browser response.     |

The slice is deliberately tiny — it only tracks *which* web-dashboard inputs are pending; the input
lifecycle itself lives in the shared `input` slice, and (per the ownership note) the Wi-Fi **hotspot
is owned by the wifi service**, not here.

## Actions & Events

The reducer reacts to the shared input actions and emits exactly one event.

| Action (in)                                    | Reducer result                                                    |
| ---------------------------------------------- | --------------------------------------------------------------- |
| `InputDemandAction(description=WebUIInputDescription())` | Append to `active_inputs` → **`WebUIInitializeEvent`** → `initialize` (`setup.py`). |
| `InputResolveAction(id=…)`                     | Drop that input; dispatch `NotificationsClearByIdAction('web_ui:pending:<id>')`. |

Per the store contract, **events are emitted only from the reducer**. `WebUIInitializeEvent` is the
only one: `setup.py`'s `initialize` handler decides whether a hotspot is needed and posts the "open
this URL" notification. Resolving an input deliberately does **not** tear down the hotspot (a
multi-step web flow keeps it up across steps).

## Runtime & Setup

`init_service()` (`setup.py:292`) is **async** (`ubo_handle.py` awaits it), builds the Quart app,
starts it as a background task, and returns a one-item `Subscriptions` list whose cleanup triggers a
graceful shutdown.

- **Server:** `Quart('ubo-app', template_folder=templates/, static_folder=web-app/dist/)`, 500 MB
  max upload, launched via `create_task(app.run_task(host=WEB_UI_LISTEN_ADDRESS,
  port=WEB_UI_LISTEN_PORT, …))`; `init_service` waits for `before_serving` before returning so the
  service is only "up" once the socket is listening.
- **State to browser:** an inner `state()` helper serializes `state.web_ui` to protobuf hex via
  `build_message(state, expected_type=GRPCWebUIState)` — the same object→message path used over
  gRPC — and is injected into the template and returned from `/status`.
- **Routes:**
  - `GET/POST /` — renders `index.jinja2`; a POST is a form submission (see input flow below).
  - `GET /status` — JSON with docker/envoy status (cached ~5s) + serialized state + pending
    downloads.
  - `GET /download/<token>` — one-shot tokened file download (temp files cleaned up after).
  - `POST /action/` — docker/envoy control (`install/run/stop docker`, `download/run/remove envoy`)
    that dispatches the corresponding `Docker*Action`s.
- **Subscriptions:** `WebUIInitializeEvent → initialize`, and `NotificationsClearEvent →
  _close_hotspot_qr_on_notification_cleared` (drops the QR page when the pending-input notification
  is cleared).

### How browser input flows back

Two paths, both landing on shared input actions:

1. **Form POST (Flask/Quart path):** `POST /` reads `request.form`; `action == 'provide'` dispatches
   `InputProvideAction(..., result=InputResult(method=InputMethod.WEB_DASHBOARD))`, `action ==
   'cancel'` dispatches `InputCancelAction`. **Uploaded files** are chunked through the same event
   path as gRPC (`FileUploadStart/Chunk/CompleteEvent` via `upload_handler`). Text inputs are fully
   on this Flask path today; see the memory note that file uploads are mid-migration to Flask POST.
2. **gRPC-web (frontend path):** the SPA also talks to the core's gRPC `StoreService` directly
   (`web-app/src/bindings/`, `store/action-dispatcher.ts`) to dispatch actions and stream state —
   the dumb-client pattern. Clients **dispatch actions**; they never emit events.

The `initialize` handler (`setup.py:215`) runs on `WebUIInitializeEvent`: if the device is offline
(no ping / no default route) it shows a "switching to hotspot" render, dispatches
`WiFiStartHotspotAction(mode='captive')`, waits for the wifi service to report it running, then posts
a sticky notification telling the user which SSID/URL to open (with a join-QR button when offline).

## User Interface

- **Browser dashboard:** the compiled SPA renders the device's current view — menus, application
  views, chat, prompts, notifications, status bar — and mirrors keypad navigation in the browser.
- **Web input forms:** any service that requests a `WebUIInputDescription` (Wi-Fi SSID/password,
  voice-command editor, model uploads, …) surfaces as a form in the dashboard; the result comes back
  as `InputProvideAction`.
- **On-device notification:** the "open `http://<host>:<port>`" prompt (and the offline hotspot
  join-QR) is the device-side half of the flow.

## System / Hardware Integration

- **HTTP server:** binds `WEB_UI_LISTEN_ADDRESS` (default `0.0.0.0`) on `WEB_UI_LISTEN_PORT`
  (default `4321`).
- **Docker CLI:** `/status` and `/action/` shell out to `docker info`/`inspect`/`ps` (timeout-guarded)
  to report and control the Envoy gRPC-web proxy (`GRPC_ENVOY_LISTEN_PORT`, default `50052`), which
  the browser needs to reach the core's gRPC service.
- **Wi-Fi hotspot:** requested from the wifi service (owner) for captive onboarding — this service
  never brings up AP mode itself.

## Cross-Service Interactions

- **input slice:** consumes `InputDemand/Resolve/Provide/CancelAction`; the primary integration.
- **wifi:** dispatches `WiFiStartHotspotAction` and reads `state.wifi.is_hotspot_running` /
  `state.ip.is_connected`; shares the QR builder in `ubo_app/utils/hotspot_qr.py`.
- **docker:** dispatches `Docker*Action`s for the Envoy proxy lifecycle.
- **notifications:** posts the "open URL" / error notifications; listens for `NotificationsClearEvent`.
- **file upload / download:** bridges browser uploads/downloads to the shared file-transfer events.

## Configuration

Environment-driven constants (from `ubo_app.constants`):

| Constant                  | Default          | Meaning                                      |
| ------------------------- | ---------------- | ------------------------------------------- |
| `WEB_UI_LISTEN_ADDRESS`   | `0.0.0.0`        | Bind address for the dashboard server.       |
| `WEB_UI_LISTEN_PORT`      | `4321`           | Dashboard HTTP port.                         |
| `WEB_UI_DEBUG_MODE`       | `False`          | Quart debug + a full-traceback error handler.|
| `WEB_UI_HOTSPOT_PASSWORD` | `ubopod-setup`   | Password shown for the captive hotspot.      |
| `GRPC_ENVOY_LISTEN_PORT`  | `50052`          | Envoy gRPC-web port the SPA connects through.|

The `main.js` cache-bust key is derived from `web-app/dist/main.js` mtime so browsers reload after a
rebuild. No secrets are stored in this slice.

## Testing & Development Notes

Related tests (unit tier runs with `uv run poe test:unit`):

| Test                                  | Tier        | What it covers                                                       |
| ------------------------------------- | ----------- | ------------------------------------------------------------------- |
| `tests/integration/test_services.py`  | Integration | `web_ui` service registers and the store snapshot matches.          |
| `tests/store/test_web_ui_reducer.py`  | Unit        | Input-demand appends + `WebUIInitializeEvent`; resolve drops the input and clears its notification. (Hotspot lifecycle now lives in `test_wifi_hotspot_reducer.py`.) |

The `web-app/` frontend is a **separate JS toolchain** (webpack + TypeScript + ESLint) with its own
scripts — it is not exercised by pytest. Its generated gRPC-web bindings (`web-app/src/bindings/`)
and `dist/` are gitignored and produced by the build.

**Maintenance when you change this service:**

- **State shape** (`WebUIState`) → regenerate store/window snapshots (`docker …
  --override-store-snapshots --override-window-snapshots`); never hand-edit snapshot files.
- **Reducer branches** (input demand/resolve) → cover in `tests/store/test_web_ui_reducer.py`;
  prefer a small pure-reducer unit test over an E2E flow.
- **Proto / RPC changes** (any field the SPA reads over gRPC or `build_message`): run `uv run poe
  proto`, then in `web-app/` run `npm run proto:compile` **and** `npm run build` so the frontend
  bindings and `dist/main.js` match the core contract (regenerating bindings alone is not enough).
- **Frontend source changes** (`web-app/src/**`) → `npm run build` (or `build:watch`) to refresh
  `dist/main.js`; `npm run lint` for ESLint. The cache-bust mtime forces the browser to reload.
- **Server routes / hotspot / docker plumbing** depend on a real network + docker CLI, so the full
  offline-onboarding path is verified on-device; on a dev host the docker calls return
  "not installed" and the hotspot cannot actually come up.

To exercise manually: open `http://<device-host>:4321` on the same network (or join the captive
hotspot when offline), trigger a web-dashboard input (e.g. Wi-Fi setup), submit the form, and
confirm the device reflects the change and the pending notification clears.
</content>
