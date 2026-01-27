# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ZHA (Zigbee Home Automation) is a hardware-independent Zigbee gateway implementation library for Home Assistant. It wraps the `zigpy` library and provides device management, entity platforms, and cluster handlers for Zigbee devices.

## Development Commands

### Setup
```bash
./script/setup  # Creates venv, installs deps, configures pre-commit hooks
source venv/bin/activate
```

### Testing
```bash
pytest                              # Run all tests
pytest tests/test_light.py          # Run single test file
pytest tests/test_light.py::test_name -v  # Run single test
pytest -x                           # Stop on first failure
pytest --cov=zha                    # Run with coverage
```

### Linting and Type Checking
```bash
ruff check .                        # Lint
ruff check . --fix                  # Auto-fix lint issues
ruff format .                       # Format code
mypy zha                            # Type check
pre-commit run --all-files          # Run all pre-commit hooks
```

### Regenerating Test Diagnostics
When modifying entities, regenerate device diagnostic JSON files:
```bash
python -m tools.regenerate_diagnostics
```

## Architecture

### Core Layer Hierarchy

```
Gateway (zha/application/gateway.py)
  └── Device (zha/zigbee/device.py) - wraps zigpy.device.Device
        └── Endpoint (zha/zigbee/endpoint.py) - wraps zigpy.Endpoint
              └── ClusterHandler (zha/zigbee/cluster_handlers/) - wraps zigpy.zcl.Cluster
                    └── PlatformEntity (zha/application/platforms/)
```

### Key Components

**Gateway** (`zha/application/gateway.py`): Central orchestrator managing Zigbee network, devices, and groups. Emits events for device lifecycle (JOINED, INTERVIEW_COMPLETE, CONFIGURED, INITIALIZED).

**Device/Endpoint** (`zha/zigbee/`): ZHA wrappers around zigpy objects providing ZHA-specific logic, state tracking, and event emission.

**ClusterHandlers** (`zha/zigbee/cluster_handlers/`): Handle specific Zigbee clusters (general, hvac, lighting, security, etc.). Each handler manages reporting configuration and attribute updates.

**Platform Entities** (`zha/application/platforms/`): Expose Zigbee functionality as typed entities (light, sensor, climate, switch, cover, fan, lock, etc.). Entities claim cluster handlers during discovery.

**Discovery** (`zha/application/discovery.py`): Maps devices/clusters to platform entities using registries. Supports device quirks via zha-quirks.

**Groups** (`zha/zigbee/group.py`): Zigbee group management with GroupEntity support for light, switch, and fan platforms.

### Key Patterns

- **Wrapper Pattern**: ZHA classes wrap zigpy objects to add ZHA-specific behavior
- **Registry Pattern**: Cluster-to-handler and device-to-platform mappings in `registries.py`
- **Dataclass Pattern**: Immutable frozen dataclasses for entity info (`BaseEntityInfo`)
- **Async Context**: Full async/await with custom `ZHAJob` scheduling system

## Testing Patterns

Tests use fixtures from `tests/conftest.py` and helpers from `tests/common.py`:

```python
async def test_something(zha_gateway):
    # Create mock device
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {1: {SIG_EP_INPUT: [ClusterIds], SIG_EP_OUTPUT: [], ...}},
        ieee="00:11:22:33:44:55:66:77"
    )
    # Join device to network
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    # Get entity for testing
    entity = get_entity(zha_device, platform=Platform.LIGHT)
```

Device diagnostic JSON files in `tests/data/devices/` can be loaded with `zigpy_device_from_json()`.

## Code Style

- Python 3.12+ required
- Ruff for linting and formatting (single quotes preferred)
- MyPy for type checking (strict mode with some disabled checks)
- All relative imports banned - use absolute imports
- Docstrings required for modules and classes
