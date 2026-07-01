# System Metrics Service (`000-system-metrics`)

## Overview

The system-metrics service samples CPU load, RAM usage, and the wall clock once a second and pushes
them into the store so the home view (CPU/RAM gauges) and the status bar (clock) can render them. It
is a thin producer: a `psutil` poll loop plus a set of view-registry dependencies that let the core
view-computation layer read the values without coupling to this service.

It loads in the `000-` (core) tier because the clock and resource gauges are part of the base UI
chrome that appears before any feature service is up. Note the directory is `000-system-metrics` but
the service id and store slice are both **`system`**. See
[`docs/architecture/UI_REDUX_ARCHITECTURE.md`](../../../docs/architecture/UI_REDUX_ARCHITECTURE.md).

## Files

| Path            | Purpose                                                                        |
| --------------- | ------------------------------------------------------------------------------ |
| `ubo_handle.py` | Registration (`service_id='system'`); returns `init_service()`'s subscriptions.|
| `setup.py`      | `psutil` metrics loop, change-thresholding, and view-registry dependencies.     |
| `reducer.py`    | Pure reducer for the `system` slice; applies `SystemMetricsUpdateAction`.       |

Store types: [`ubo_app/store/services/system.py`](../../store/services/system.py).

## State

Slice: `state.system` — [`SystemState`](../../store/services/system.py):

| Field         | Type    | Meaning                                        |
| ------------- | ------- | ---------------------------------------------- |
| `cpu_percent` | `float` | Latest CPU utilization (0.0 default).          |
| `ram_percent` | `float` | Latest RAM utilization (0.0 default).          |
| `clock`       | `str`   | Local time as `"HH:MM"` (empty default).       |

## Actions & Events

| Action                      | Reducer result                                        |
| --------------------------- | ----------------------------------------------------- |
| `SystemMetricsUpdateAction` | Patches `cpu_percent`, `ram_percent`, `clock`.        |

The reducer emits **no events** and dispatches no cross-service actions — it is a pure state-mapper.

## Runtime & Setup

`init_service()` (`setup.py:77`) registers the view dependencies/providers, takes one immediate
reading, and starts the poll loop:

```python
unregister_cpu = register_home_view_dependency('system:cpu', lambda s: s.system.cpu_percent)
unregister_ram = register_home_view_dependency('system:ram', lambda s: s.system.ram_percent)
unregister_clock = register_status_bar_dependency('system:clock', lambda s: s.system.clock)
register_home_view_data_provider('system:cpu', lambda s: ('cpu_percent', s.system.cpu_percent))
register_home_view_data_provider('system:ram', lambda s: ('ram_percent', s.system.ram_percent))

read_metrics()
end_event = asyncio.Event()
create_task(_monitor_metrics(end_event))
```

- `_monitor_metrics()` loops every 1 s calling `read_metrics()` until `end_event` is set.
- `read_metrics()` reads `psutil.cpu_percent`/`virtual_memory().percent` and the local-timezone
  `HH:MM`, and **only dispatches `SystemMetricsUpdateAction` when a value changed meaningfully** —
  CPU/RAM must move more than `_METRICS_THRESHOLD` (0.5 percentage points) or the minute must roll
  over. This throttling avoids flooding autoruns/view recomputation. The last-dispatched values live
  in a module-level `_last` dict (a container, not a `global`).

`init_service()` returns `[end_event.set, *unregister_callbacks]` so the loop stops and the view
dependencies deregister cleanly on teardown.

## User Interface

Headless — no settings entry, menu, or pages. Its output surfaces through the core view-computation
layer: the `system:cpu`/`system:ram` home-view dependencies feed `HomeViewData` and `system:clock`
feeds the status bar. The GUI/TUI/web clients render whatever those computed views contain.

## System / Hardware Integration

- **`psutil`** for CPU and virtual-memory percentages.
- Wall clock uses the host's local timezone (`datetime.now(...).astimezone()`), rendered as `HH:MM`.

No GPIO/I2C or privileged calls.

## Cross-Service Interactions

None at the action level — it neither dispatches to nor reads other services' slices. Its values are
*consumed* by the core view/status-bar computation (via the view registry), which is why it lives in
the core tier alongside display and keypad.

## Configuration

No env vars or secrets. Constants: `_METRICS_THRESHOLD = 0.5` (dispatch dead-band) and the 1-second
poll interval in `_monitor_metrics`.

## Testing & Development Notes

Related tests:

| Test                                   | Tier        | What it covers                                                             |
| -------------------------------------- | ----------- | ------------------------------------------------------------------------- |
| `tests/store/test_view_computation.py` | Unit        | Confirms `cpu_percent`/`ram_percent` flow through to `HomeViewData` (seeds the `system` slice and asserts the computed view). |
| `tests/integration/test_services.py`   | Integration | Asserts the `system` service registers and the store snapshot matches.     |

> There is **no dedicated unit test** for the system-metrics reducer or the `read_metrics`
> thresholding. Both are trivial to cover: feed `SystemMetricsUpdateAction` and assert the resulting
> `SystemState`, or monkeypatch `psutil` + `store.dispatch` and assert the dead-band suppresses
> sub-threshold changes. Adding `tests/store/test_system_metrics.py` is a good first contribution.

**Maintenance when you change this service:**

- **State shape** (`SystemState`) → regenerate store/window snapshots (never hand-edit them);
  updates `test_services.py`.
- **View wiring** (dependency/provider keys such as `system:cpu`) → verify against
  `tests/store/test_view_computation.py`, which asserts the computed home view.
- **Reducer branch** or **thresholding logic** → add a small pure unit test rather than an E2E flow.
- The `psutil` readings depend on the host; values differ between a dev machine and a device, but the
  slice/plumbing behavior is platform-independent.

To exercise manually: watch the status-bar clock update each minute and the home-view CPU/RAM gauges
move under load.
