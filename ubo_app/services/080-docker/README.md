# Docker Service (`080-docker`)

## Overview

The Docker service turns the device into a small container appliance: it installs/starts the Docker
daemon, manages a registry of pre-defined **apps** (single containers *and* multi-container
compositions such as Home Assistant, Node-RED, n8n, Immich, OpenClaw), and drives their full
lifecycle — fetch → run → stop → remove — with live status, port monitoring, and LAN-exposure
controls. It also renders compose files from *persisted intent* (Zigbee passthrough, host-network
discovery, LAN binding) rather than storing brittle compose fragments.

It loads in the `080-` tier (after core, network, and access services) because containers depend on
networking and privileged installation being in place.

## Files

| Path                     | Purpose                                                                       |
| ------------------------ | ----------------------------------------------------------------------------- |
| `ubo_handle.py`          | Registration; async `setup` returns `init_service()`'s subscription list.     |
| `setup.py`               | Runtime hub (~1150 lines): daemon check, event subscriptions, app reconcile.  |
| `reducer.py`             | `combine_reducers` of a `service` sub-reducer + one `image` reducer per app.   |
| `menus.py`               | Dynamic menu builders for the Apps list and per-app screens.                   |
| `docker_composition.py`  | Compose rendering (from intent) + `docker compose` up/down/pull for stacks.    |
| `docker_container.py`    | Single-container run/stop/remove and status checks.                            |
| `docker_image.py`        | Image pull/remove and availability checks.                                     |
| `port_monitor.py`        | Probes an app's first host port until it serves HTTP → flips status to RUNNING.|
| `calculate_progress.py`  | Parses pull/build output into progress for the UI.                             |
| `apps/`                  | Per-app `ContainerEntry` definitions + the aggregating `IMAGES` registry.      |
| `assets/envoy.yaml.tmpl` | Template asset consumed by the Envoy app.                                      |

Store types: [`ubo_app/store/services/docker.py`](../../store/services/docker.py).

## State

Slice: `state.docker` — [`DockerState`](../../store/services/docker.py), a
`BaseCombineReducerState`:

- **`service`** — [`DockerServiceState`](../../store/services/docker.py): daemon `status`
  (`DockerStatus`), registry `usernames`, and per-app *intent* maps that are all persisted:
  `expose_to_lan`, Zigbee (`zigbee_enabled`/`zigbee_adapter_by_id`), and `host_network_enabled`.
- **One `ImageState` per app** — keyed by app id: `status` (`DockerItemStatus`), `docker_id`,
  `container_ip`, `ports`, plus `is_fetching`/`is_available`/`is_running` helpers.

Two enums drive the machine: `DockerStatus` (daemon: `NOT_INSTALLED`→`NOT_RUNNING`→`RUNNING`…) and
`DockerItemStatus` (per app: `NOT_AVAILABLE`→`FETCHING`→`AVAILABLE`→`CREATED`→`STARTING`→`RUNNING`,
plus `ERROR`/`PROCESSING`).

## Actions & Events

The reducer is a strict **action-in → event-out** mapper (events are emitted only from reducers);
every side-effecting operation is an event handled in `setup.py`. This keeps the reducer pure and
puts all blocking Docker I/O off the store's critical path.

| Action                        | Event emitted → handler in `setup.py`                        |
| ----------------------------- | ------------------------------------------------------------ |
| `DockerInstallAction`         | `DockerInstallEvent` → `install_docker`                      |
| `DockerStart/StopAction`      | `DockerStart/StopEvent` → `start_docker`/`stop_docker`       |
| `DockerImageFetchAction`      | `…FetchEvent` / `…FetchCompositionEvent` (composition-aware) |
| `DockerImageRunAction`        | `…RunContainerEvent` / `…RunCompositionEvent`                |
| `DockerImageStopAction`       | `…StopContainerEvent` / `…StopCompositionEvent`              |
| `DockerImageRemoveAction`     | `…RemoveEvent` / `…RemoveCompositionEvent`                   |
| `DockerImageReleaseAction`    | `…ReleaseCompositionEvent` (stop + cleanup)                  |
| `DockerImageSetExposeToLanAction` | `DockerImageRebindEvent` → `handle_rebind` (recreate so binding takes effect) |

Non-event actions patch state directly: `DockerSetStatusAction`, `DockerImageSetStatusAction`,
`DockerImageSetDockerIdAction`, `DockerImageUpdateMetadataAction`, `DockerStoreUsernameAction`,
`DockerSetZigbeeIntentAction`, `DockerSetHostNetworkAction`.

The per-app reducer is created on `CombineReducerInitAction` (payload carries `label`) and emits a
`DockerImageRegisterAppEvent` so `setup.py` can wire up that app's menu/monitors.

## Runtime & Setup

`init_service()` (`setup.py:1012`) is **async** (`ubo_handle.py` awaits it) and:

1. Registers persistent stores for every `service` intent field, the Apps menu title, path matchers,
   the "Add New App" regular-app entry, and the Docker settings entries (Service, Registries).
2. Subscribes each lifecycle event to its handler (the table above) — this is the behavioral core.
3. Calls `_load_images()` and `await check_docker()`, then starts `monitor_unit('docker.socket', …)`
   so daemon up/down transitions re-sync automatically.

**Reconciliation at boot** — `sync_docker_containers()` (`setup.py:~300`) scans existing containers
and, for every registered image, refreshes status so consumers reading the store *without* opening
the Docker menu don't see a stale `NOT_AVAILABLE`. It is deliberately careful:

- **Containers/images:** `start_event_monitor(image_id)` (idempotent, live updates, no polling) +
  `check_container(image_id)`.
- **Compositions:** `check_composition(id)` is **status-only** at boot — it does *not* re-render
  (`prepare_app`) or recreate, since prepare hooks may fetch over the network and a blanket recreate
  would restart unrelated running stacks. Compose files are re-rendered lazily at run time
  (`run_composition`). Home Assistant additionally runs `heal_home_assistant_zigbee()` to recover a
  Zigbee-bricked start.

`prepare_app()` (`docker_app.py`) runs each app's optional `prepare` hook (sync or async) before a
run; a `False` result aborts the run, and composition metadata (e.g. instructions) is loaded from
`metadata.json` and pushed via `DockerImageUpdateMetadataAction`.

## User Interface

- **Apps menu:** each installed app appears as a regular app; `menus.py` builds per-app dynamic
  menus (fetch/run/stop/remove, LAN toggle, per-app custom `menu_actions`).
- **Settings:** `SettingsCategory.DOCKER` entries for *Service* (install/start/stop) and
  *Registries* (stored usernames); plus an "Add New App" entry to import a composition
  (`docker:import_composition`).
- **Path matcher:** `_docker_path_matcher` resolves both app and settings deep-links.
- **Progress/status:** pull/build output is parsed (`calculate_progress.py`) and `port_monitor.py`
  probes the app's HTTP port to advance `CREATED/STARTING` → `RUNNING`.

## System / Hardware Integration

- **Docker SDK** (`docker.from_env()`) for daemon ping, image, and container operations; blocking
  calls are dispatched off the loop.
- **`docker compose`** for compositions (`docker_composition.py`), with compose files rendered under
  `CONFIG_PATH/docker_compositions/<id>/` from persisted intent.
- **Privileged install** via `is_package_installed`/system manager; daemon lifecycle observed with
  `monitor_unit('docker.socket', …)`.
- **Shared bridge network `ubo_net`** — an external Docker network Ubo-managed stacks attach to as a
  cross-stack bus (e.g. reaching the bundled Mosquitto broker); bootstrapped idempotently.
- **Hardware passthrough:** the Zigbee USB coordinator (`/dev/serial/by-id`) is re-derived into
  compose at render time, never persisted as raw compose lines — as is Home Assistant's network
  mode (`ubo_net` bridge, or the host stack for mDNS/SSDP discovery).

## Cross-Service Interactions

- Reads IP interface data (`IpUpdateInterfacesAction` referenced by the image reducer) and consumes
  core menu/app/settings actions (`RegisterRegularAppAction`, `RegisterSettingAppAction`).
- Dispatches notifications (install/error/broker-needs-HA warnings) into `010-notifications`.
- Other services consume this slice (e.g. the assistant checks Ollama image availability), which is
  precisely why boot reconciliation avoids leaving stale `NOT_AVAILABLE`.
- Related work lives across the ecosystem: the HA→Compose bus, bundled Mosquitto, Node-RED, and the
  gRPC-LAN Envoy proxy are all modeled as apps here.

## Configuration

- Persisted (via `register_persistent_store`): `docker_usernames`, `docker_expose_to_lan`,
  `docker_zigbee_enabled`, `docker_zigbee_adapter_by_id`, and `docker_host_network_enabled`.
- `COMPOSITIONS_PATH = CONFIG_PATH / 'docker_compositions'`; shared network name `UBO_NET`
  (`ubo_net`); per-app `ContainerEntry` flags: `supports_lan_toggle`, `requires_mqtt`,
  `is_composition`, `secret_keys`, and the `prepare`/`cleanup`/`apply_lan_config` hooks.

## Testing & Development Notes

Related tests (unit tier runs with `uv run poe test:unit`):

| Test                                        | Tier        | What it covers                                                    |
| ------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| `tests/integration/test_services.py`        | Integration | `docker` service registers; store snapshot matches.             |
| `tests/store/test_docker_image_matching.py` | Unit        | Mapping running containers back to registered `IMAGES`.         |
| `tests/store/test_docker_port_binding.py`   | Unit        | Host-port binding derivation (`apps/_port_binding.py`).         |
| `tests/store/test_docker_lan_toggle.py`     | Unit        | `expose_to_lan` intent → loopback vs `0.0.0.0` + rebind.       |
| `tests/store/test_docker_zigbee_intent.py`  | Unit        | Zigbee passthrough intent → render-time compose derivation.    |
| `tests/store/test_docker_app_categories.py` | Unit        | App categorization in the menu.                                 |
| `tests/store/test_docker_{home_assistant,hermes,node_red,envoy,pangolin}_app.py` | Unit | Per-app `ContainerEntry` render/prepare behavior. |

**Maintenance when you change this service:**

- **Adding an app:** create `apps/<name>.py` exporting `ENTRY: ContainerEntry`, add it to the
  `IMAGES` list in `apps/__init__.py` (the per-app reducer, menu, and monitors wire up
  automatically), and add a `tests/store/test_docker_<name>_app.py` if the app has non-trivial
  prepare/render logic.
- **`IMAGES` or state shape changes** feed snapshot tests — regenerate store/window snapshots (see
  the repo's Docker test workflow); never hand-edit snapshots.
- **Port/LAN/intent logic** → update the matching `test_docker_port_binding` / `_lan_toggle` /
  `_zigbee_intent` test.
- **Reducer invariants to preserve:** every `DockerItemStatus` (including `CREATED`) is handled,
  blocking Docker I/O stays off the store loop, and `prepare_app()` returning `False` aborts the
  run. The reducer is pure — prefer covering new lifecycle branches with a `tests/store` unit test
  over the heavier integration tier.
- Real Docker operations require a working daemon, so full lifecycle is verified on-device or in
  Docker-based integration runs; on a dev host daemon calls are unavailable/mocked.
