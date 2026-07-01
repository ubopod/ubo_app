# Camera Service (`040-camera`)

## Overview

The camera service owns image capture on the device: it detects available camera sources
(local USB/Picamera hardware *and* remote clients that push frames over gRPC), runs a live
viewfinder, and decodes QR/bar-codes to satisfy the input system's `QRCodeInputDescription`
demands (e.g. Wi-Fi onboarding QR). It abstracts the underlying hardware behind a
`CameraBackend` protocol so the same capture loop works on a Raspberry Pi (Picamera2) and on a
dev host (OpenCV).

It loads in the `040-` hardware tier — after core, display and networking, but before the
`050-`/`090-` consumers that rely on QR-based input flows, so a camera is available whenever a
service raises an `InputDemandAction` carrying a `QRCodeInputDescription`.

For the action/event/store model this doc references throughout, see
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## Files

| Path                    | Purpose                                                                        |
| ----------------------- | ------------------------------------------------------------------------------ |
| `ubo_handle.py`         | Registration; registers the reducer and returns `init_service()`'s subscriptions. |
| `setup.py`              | Runtime: backend init, viewfinder session, QR decode, detection, dynamic menu, driver install. |
| `reducer.py`            | Pure reducer for the `camera` slice; input-queue handling + action→event mapping. |
| `camera_backend.py`     | `CameraBackend` `Protocol` (start/stop/close/capture_array/configure/set_controls). |
| `opencv_backend.py`     | OpenCV `VideoCapture` backend for macOS/Linux dev hosts.                        |
| `picamera2_backend.py`  | Picamera2 backend for Raspberry Pi (RGB888, autofocus/AWB controls).           |
| `utils.py`              | Camera-index detection helpers (`detect_available_cameras[_picamera2]`).        |
| `pages.py`              | Thin shim re-exporting `CAMERA_MENU_ID`; the menu is now fully dynamic.         |

Store types: [`ubo_app/store/services/camera.py`](../../store/services/camera.py).

## State

Slice: `state.camera` — [`CameraState`](../../store/services/camera.py):

| Field                          | Type                          | Meaning                                                             |
| ------------------------------ | ----------------------------- | ------------------------------------------------------------------ |
| `queue`                        | `list[QRCodeInputDescription]`| Pending QR-code input demands; the head drives the prompt/viewfinder. |
| `selected_source_id`           | `str`                         | Active source id, `local:<index>` or `remote:<uuid>` (persisted).  |
| `available_cameras`            | `tuple[CameraSource, ...]`    | Merged local + remote source list from the last detection cycle.   |
| `pending_remote_registrations` | `tuple[CameraSource, ...]`    | Staging area for remote clients answering a detect advertise.      |
| `camera_type`                  | `CameraType`                  | `default` / `autofocus` / `fixed-focus` (persisted; drives driver + AF). |

`selected_source_id` is migrated from the legacy `camera_selected_index` int key on first init
(`_resolve_initial_source_id`).

## Actions & Events

Events are emitted **only from the reducer**; `setup.py` subscribes and performs the async /
capture / privileged side effects.

| Action (in)                     | Reducer result                                                          |
| ------------------------------- | ---------------------------------------------------------------------- |
| `InputDemandAction` (QR desc.)  | Appends to `queue`; prompts a "QR Code" notification if queue was empty. |
| `InputResolveAction`            | Pops/removes the matching queue entry (`pop_queue` clears the notification). |
| `CameraStartViewfinderAction`   | → `CameraStartViewfinderEvent(source_id=selected)`.                    |
| `CameraDetectAction`            | → `CameraDetectEvent` (probe local) **and** `CameraDetectAdvertiseEvent` (invite remotes). |
| `CameraSetSelectedSourceAction` | Sets `selected_source_id`.                                             |
| `CameraSetIndexAction`          | Deprecated shim → `selected_source_id='local:N'`.                      |
| `CameraRegisterRemoteAction`    | Adds/updates a remote source in `pending_remote_registrations`.        |
| `CameraSetAvailableCamerasAction` | Publishes the merged list, re-validates selection, clears staging.   |
| `CameraReportImageAction`       | → `CameraReportImageEvent` (remote gRPC frame → same decode path as local). |
| `CameraReportBarcodeAction`     | Matches the queue head's `pattern`; on hit dispatches `InputProvideAction`. |
| `CameraInstallDriverAction`     | Sets `camera_type`; → `CameraInstallDriverEvent`.                      |
| `CameraRestoreDefaultAction`    | Resets `camera_type`; → `CameraRestoreDefaultEvent`.                   |

## Runtime & Setup

`init_service()` (`setup.py:760`) registers the Settings entry + path matcher, kicks off an
initial `detect_and_update_cameras()`, registers the two persistent stores, and returns the
event subscriptions.

- **Backend selection** — `initialize_camera()` (`setup.py:231`) picks the backend by platform:
  on `IS_RPI` it imports `PiCamera2Backend`, otherwise `OpenCVCameraBackend`; both are constructed
  at `WIDTH*2 × HEIGHT*2` and started. A failure is reported via `report_service_error()` and
  returns `None`, so the viewfinder degrades gracefully.
- **Viewfinder session** — `start_camera_viewfinder_session()` (`setup.py:182`) opens a
  `frame_stream` render (`stream_id='camera:viewfinder'`), runs a `_RepeatingTimer` at
  `VIEWFINDER_INTERVAL` that calls `feed_viewfinder`, and an autorun on `selected_source_id` swaps
  the local backend (remote sources have no local backend — frames arrive over gRPC). A
  `StackChangedEvent` subscriber tears the session down and cancels a still-pending input when the
  viewfinder leaves the stack.
- **Frame handling** — `_handle_report_image` (`setup.py:342`) runs for *every*
  `CameraReportImageEvent` (local timer or remote gRPC), drops frames whose `source_id` isn't the
  selected source, decodes with `pyzbar`, and forwards the frame to the display via
  `FrameStreamDataEvent`.
- **Detection** — `detect_and_update_cameras()` (`setup.py:589`) probes local indices, waits
  `REMOTE_REGISTRATION_WINDOW` for remote clients to answer the advertise, then dispatches
  `CameraSetAvailableCamerasAction` with the merged list.
- **Dynamic menu** — `update_camera_dynamic_menu` (`setup.py:700`) is an `@store.autorun` on the
  whole slice that rebuilds `CAMERA_MENU_ID` and (re)registers `camera:select:<id>` handlers.

## User Interface

- **Settings entry:** `RegisterSettingAppAction` under `SettingsCategory.HARDWARE`.
- **Dynamic menu:** `CAMERA_MENU_ID = 'camera:main'` (dumb-UI `UpdateDynamicMenuAction`): one row
  per source (green background = selected, `󰀂` glyph for remote), plus "Detect Cameras" and
  "View Finder".
- **Viewfinder:** an `OpenRenderAction(kind='frame_stream', stream_id='camera:viewfinder')` full
  screen fed by `FrameStreamDataEvent`.
- **QR prompt:** `prompt_notification` (`reducer.py:66`) shows a sticky `camera:qrcode:<id>`
  notification with an "Open Camera" action; `on_close_id` cancels the input.
- **Path matcher:** `create_settings_path_matcher('camera:', CAMERA_MENU_ID)`.

## System / Hardware Integration

- **Two backends** behind `CameraBackend`: Picamera2 (RGB888, `AwbEnable`, autofocus when
  `camera_type == 'autofocus'`) on the Pi; OpenCV `VideoCapture` (BGR→RGB, 180° rotate, warm-up
  frames) elsewhere.
- **Remote sources:** clients (iOS/web) that answer `CameraDetectAdvertiseEvent` with
  `CameraRegisterRemoteAction` and then push frames as `CameraReportImageAction` over gRPC — they
  cannot emit events directly, so the reducer translates the action into `CameraReportImageEvent`.
- **Privileged driver ops:** `send_command('camera', 'install_driver'|'restore_default', ...)` to
  the system manager (both prompt a reboot on success).
- **QR decode:** `pyzbar`; PNG/text mock inputs at `/tmp/qrcode_input.{png,txt}` short-circuit the
  capture path off-device for tests.

## Cross-Service Interactions

- **Input system:** consumes `InputDemandAction`/`InputResolveAction`/`InputProvideEvent` and
  produces `InputProvideAction`/`InputCancelAction` — this is the service's primary role.
- **Display/render:** emits `FrameStreamDataEvent` and `OpenRenderAction`/`StackPopItemAction`.
- **Notifications:** driver-install/restore progress + QR prompts into `010-notifications`.
- **Core:** `RegisterSettingAppAction`, `UpdateDynamicMenuAction`, the action/view registries.

## Configuration

- Persisted (`register_persistent_store`): `camera_selected_source_id`, `camera_type`.
- Constants: `CAMERA_MENU_ID`, `VIEWFINDER_INTERVAL`, `THROTTL_TIME`,
  `REMOTE_REGISTRATION_WINDOW`; capture size derives from `WIDTH`/`HEIGHT` in `ubo_app.constants`.

## Testing & Development Notes

| Test                                   | Tier        | What it covers                                                       |
| -------------------------------------- | ----------- | ------------------------------------------------------------------- |
| `tests/store/test_camera_reducer.py`   | Unit        | `CameraReportImageAction` → `CameraReportImageEvent` pass-through (the remote-frame seam). |
| `tests/fixtures/mock_camera.py`        | Fixture     | Mocks capture by dropping a PNG at `/tmp/qrcode_input.png`; used by higher tiers to feed a QR frame without hardware. |
| `tests/integration/test_services.py`   | Integration | Asserts the `camera` service registers and the store snapshot matches. |

> The reducer's detection/selection and QR-match branches have **no dedicated unit test** beyond
> the remote-frame pass-through — they're only exercised via the mock-camera fixture in higher
> tiers. A pure `tests/store` test feeding `CameraReportBarcodeAction` against a queued
> `QRCodeInputDescription.pattern` would be a good first addition.

**Maintenance when you change this service:**

- **State shape** (`CameraState`) or the dynamic-menu output → regenerate store/window snapshots
  (`docker … --override-store-snapshots --override-window-snapshots`); never hand-edit snapshots.
- **Reducer branch** (new action/event, QR-match logic, remote-registration merge) → add/extend a
  `tests/store/test_camera_reducer.py` case; prefer a small pure-reducer test over a viewfinder E2E.
- **Backend changes** (`opencv_backend.py`/`picamera2_backend.py`) → verify on-device: Picamera2
  isn't importable off the Pi, and `IS_RPI` selects the backend, so real capture is only meaningful
  on hardware. Off-device, drive frames through `tests/fixtures/mock_camera.py`.
- **New source kinds / gRPC frame contract** → keep `CameraReportImageAction` →
  `CameraReportImageEvent` in lock-step and cover it in the reducer test.

To exercise manually: Settings → Hardware → Camera → Detect Cameras, pick a source, open View
Finder, and confirm QR scanning resolves a pending input (e.g. a Wi-Fi QR onboarding prompt).
