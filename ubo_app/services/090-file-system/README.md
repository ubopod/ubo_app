# File System Service (`090-file-system`)

## Overview

The file system service is the device's file browser and transfer hub: it renders directories as
dynamic menus, previews files (text/image/audio/video), performs copy/move/remove, provides a
reusable **path selector** for other services' `PathInputDescription` demands, and moves bytes to
and from the web UI via chunked uploads and tokenized downloads. Blocking filesystem/`shutil`/
`ffmpeg` work happens in event handlers, keeping the reducer pure.

It loads in the `090-` application tier — it's a leaf consumer that depends on notifications,
audio, input, and the core render/stack being available.

For the action/event/store model, see
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## Files

| Path                  | Purpose                                                                              |
| --------------------- | ----------------------------------------------------------------------------------- |
| `ubo_handle.py`       | Registration; async `setup` registers the reducer and calls `init_service()`.       |
| `setup.py`            | Runtime: app/path-matcher registration, copy/move/remove handlers, upload/download/video subscriptions. |
| `reducer.py`          | Pure reducer for `file_system` + pass-through of `file_upload`/`file_download` actions to events. |
| `constants.py`        | `SELECTOR_APPLICATION_ID` notification-id template.                                  |
| `file_application.py` | The browser UI: dynamic directory menus, file previews, copy/move/remove/upload/download actions. |
| `download_handler.py` | Prepares a file (or zips a directory) and registers a download token for the web UI. |
| `upload_handler.py`   | Server-side chunked-upload session manager (temp file assembly, validation, TTL cleanup). |
| `video_streamer.py`   | Streams video frames (cv2) + audio (ffmpeg PCM) as a `file-system:video` render.     |

Store types: [`ubo_app/store/services/file_system.py`](../../store/services/file_system.py),
plus the companion [`file_upload.py`](../../store/services/file_upload.py) and
[`file_download.py`](../../store/services/file_download.py) slices (action/event carriers).

## State

Slice: `state.file_system` — [`FileSystemState`](../../store/services/file_system.py):

| Field            | Type                          | Meaning                                                            |
| ---------------- | ----------------------------- | ----------------------------------------------------------------- |
| `queue`          | `list[PathInputDescription]`  | Pending path-selector input demands; the head drives the selector. |
| `selector_depth` | `int`                         | Menus pushed during a selector session, so they can be popped as a group. |

The `file_upload`/`file_download` slices are **stateless** — their actions exist only to be mapped
to events (transport lives in the handlers and `ubo_app/utils/file_upload.py` /
`ubo_app/utils/file_download.py`).

## Actions & Events

Events are emitted **only from the reducer**; `setup.py`'s handlers do the blocking I/O.

| Action (in)                     | Event emitted → handler                                              |
| ------------------------------- | ------------------------------------------------------------------- |
| `FileSystemCopyAction`          | `FileSystemCopyEvent` → `handle_copy_event` (`shutil.copy*`).       |
| `FileSystemMoveAction`          | `FileSystemMoveEvent` → `handle_move_event` (`shutil.move`).        |
| `FileSystemRemoveAction`        | `FileSystemRemoveEvent` → `handle_remove_event` (`unlink`/`rmtree`). |
| `InputDemandAction` (path desc.)| `FileSystemSelectEvent` → `handle_open_path_event` (opens selector). |
| `InputResolveAction`            | `pop_queue`: clears notification, pops `selector_depth`, emits `FileSystemSelectorCleanupEvent`. |
| `FileSystemReportSelectionAction`| `InputProvideAction` + `FileSystemSelectorCleanupEvent`.           |
| `FileSystemSelectorPushedAction`| Increments `selector_depth` (state-only).                          |
| `FileUploadStart/Chunk/CompleteAction` | matching `FileUpload*Event` → `handle_upload_*`.             |
| `FileDownloadRequestAction`     | `FileDownloadRequestEvent` → `handle_download_request`.             |
| `FileDownloadReadyAction`       | `FileDownloadReadyEvent` (web UI picks up the token).              |

`FileSystemVideoFrameEvent` is emitted directly by `video_streamer.py` (alongside
`FrameStreamDataEvent`), not from the reducer.

## Runtime & Setup

`init_service()` (`setup.py:54`) registers the app, path matcher, and all event subscriptions.

- **App + matcher:** `RegisterRegularAppAction` ("File System", category `Files`, action
  `file-system:open`) and `register_path_menu_matcher('file-system:paths', …)` matching
  `file-system:dir:<path>` menu ids.
- **Copy/move/remove:** subscribed handlers run `shutil` synchronously and emit result
  notifications; a `FileSystemEvent` subscription in `file_application._items_generator` refreshes
  the affected directory menu.
- **Uploads (chunked, over gRPC):** `handle_upload_start/chunk/complete` (`upload_handler.py`)
  manage a per-`upload_id` `_UploadSession` — a pre-allocated temp file written at chunk offsets,
  validated (size/index/duplicate), progress-notified, then moved to the target or registered via
  `register_completed_upload` for a waiter. Sessions older than `SESSION_TTL` (10 min) are reaped.
- **Downloads (tokenized, for the web UI):** `handle_download_request` (`download_handler.py`)
  zips directories to a temp archive (or serves a file directly), calls `register_download(token,
  …)`, and dispatches `FileDownloadReadyAction` so the browser can fetch the token.
- **Video preview:** `_open_video` opens a `file-system:video` `frame_stream`;
  `start_video_stream` (`video_streamer.py`) runs two daemon threads — cv2 frame decode →
  `FrameStreamDataEvent`, and `ffmpeg` PCM extraction → `AudioPlayAudioSequenceAction`. A
  `StackChangedEvent` subscription (`register_video_stream_cleanup`) stops streaming when the
  viewer leaves the stack.

> **Routing note:** file bytes currently move over **gRPC** — uploads as chunked
> `FileUpload*Action`s, downloads as a token the web UI resolves. Text-form input already goes
> through Flask; routing file uploads through Flask POST is a tracked phase-2 item.

## User Interface

- **Regular app:** "File System" (`RegisterRegularAppAction`, `app_category='Files'`).
- **Dynamic directory menus:** `file-system:dir:<path>` (`file_application._items_generator`),
  rebuilt on directory `mtime` change and on `FileSystemEvent`. Directories recurse via
  `file-system:open:<path>`; files open a preview.
- **Previews (`_show_file`):** image → `OpenRenderAction(kind='image_viewer')`, audio → WAV
  playback via the audio service, video → `file-system:video` stream, other → `text_viewer`.
- **Path selector:** driven by `PathInputDescription`; `_resolve_select_handlers` switches between
  browse ("Info") and select ("Select") modes based on `accepts_files`/`accepts_directories`.
- **Transfer actions:** copy/move (prompt a destination via `ubo_input` path selector), remove
  (confirmation notification), upload (`WebUIInputDescription` FILE field), download.

## System / Hardware Integration

- **`shutil`** for copy/move/remove/zip; **`tempfile`** for upload staging and zip archives.
- **`ffmpeg`** (subprocess, `s16le` PCM) + **OpenCV** (`cv2.VideoCapture`) for video preview; a
  missing `ffmpeg` degrades to silent video.
- **`wave`** for WAV audio playback in the browser.

## Cross-Service Interactions

- **Input system:** consumes `InputDemandAction`/`InputResolveAction`, produces
  `InputProvideAction`/`InputCancelAction` — the reusable path selector other services depend on.
- **Notifications (`010`):** progress/result notifications for every operation.
- **Audio (`000`):** `AudioPlayAudioSequenceAction`/`AudioStopPlaybackAction` for audio + video
  playback.
- **Core/display:** `OpenRenderAction`, `FrameStreamDataEvent`, `StackPushMenuAction`,
  `StackPopAction`, `UpdateDynamicMenuAction`, `RegisterRegularAppAction`.
- **Web UI (`090-web-ui`):** consumes the download token and drives chunked uploads.

## Configuration

No env vars or secrets. Constants: `SELECTOR_APPLICATION_ID` (`constants.py`), `SESSION_TTL`
(`upload_handler.py`), `PREVIEW_WIDTH/HEIGHT`, `FRAME_INTERVAL`, `AUDIO_RATE`
(`video_streamer.py`), `FILE_VIEWER_SIZE_LIMIT`, `IMAGE_VIEWER_MAX_DIMENSION`
(`file_application.py`).

## Testing & Development Notes

| Test                                       | Tier        | What it covers                                                   |
| ------------------------------------------ | ----------- | --------------------------------------------------------------- |
| `tests/store/test_file_system_reducer.py`  | Unit        | Reducer branches: copy/move/remove events, selector queue, `pop_queue`. |
| `tests/store/test_file_upload.py`          | Unit        | Chunked-upload reducer pass-through + server-side temp-file assembly. |
| `tests/store/test_file_upload_timeout.py`  | Unit        | Chunked-upload waiter failure paths (missing chunks, timeout, TTL). |
| `tests/flows/test_file_system.py`          | Flow (E2E)  | Move → copy back → remove, all via real keypad presses (Docker/on-device). |
| `tests/integration/test_services.py`       | Integration | Asserts the `file_system` service registers and the snapshot matches. |

**Maintenance when you change this service:**

- **State shape** (`FileSystemState`) or menu/preview output → regenerate store/window snapshots
  (never hand-edit them); this feeds `test_services.py` and `test_file_system.py`.
- **Reducer branch** (new action/event, selector-depth logic) → add a case to
  `tests/store/test_file_system_reducer.py`.
- **Upload/assembly changes** (`upload_handler.py`, chunk validation, session lifecycle) → update
  `tests/store/test_file_upload.py` and the failure-path `test_file_upload_timeout.py`.
- **Download/zip or video/ffmpeg changes** have **no dedicated unit test** — verify manually;
  `ffmpeg`/`cv2`/`wave` need real files, so preview behavior is checked on-device or in Docker.
- Prefer a small pure-reducer or handler unit test over extending the keypad flow (which runs
  reliably only in Docker/on-device).

To exercise manually: open the File System app, browse a directory, preview a text/image/audio/
video file, then copy → move → remove a file and confirm the result notifications; from the web UI,
upload a file into a directory and download a file/folder.
