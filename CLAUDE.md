# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ZHA CLI is a command-line interface tool for managing Zigbee coordinators and devices. It uses the [ZHA](https://github.com/zigpy/zha) library for Zigbee communication.

## Development Commands

### Setup
```bash
pip install -e .
```

### Running
```bash
zha-cli           # Run the CLI
zha-cli -v        # Run with verbose logging
```

### Linting
```bash
ruff check .      # Lint
ruff check . --fix  # Auto-fix lint issues
ruff format .     # Format code
```

## Architecture

### File Structure

```
zha_cli/
├── __init__.py           # Module exports
├── main.py               # Entry point and main menu loop
├── coordinator_probe.py  # Serial port enumeration and radio probing
├── network_manager.py    # Gateway lifecycle management
├── device_pairing.py     # Pairing mode and device events
├── device_control.py     # Entity control (on/off)
└── ui.py                 # Terminal UI helpers using rich
```

### Key Components

**coordinator_probe.py**: Detects Zigbee coordinators by probing serial ports with each RadioType's controller.

**network_manager.py**: Manages the ZHA Gateway lifecycle - starts/stops the Zigbee network.

**device_pairing.py**: Handles permit join for pairing new devices, subscribes to device events.

**device_control.py**: Controls device entities (turn on/off for switches and lights).

**ui.py**: Rich-based terminal UI with tables and prompts.

**main.py**: Main CLI class with interactive menu.

### Dependencies on ZHA

This CLI depends on the `zha` library from PyPI. Key imports:
- `zha.application.gateway.Gateway` - Network management
- `zha.application.helpers` - Configuration dataclasses
- `zha.application.const.RadioType` - Coordinator types
- `zha.application.platforms` - Entity platform base classes

## Code Style

- Python 3.12+ required
- Ruff for linting and formatting
- Use absolute imports (`from zha_cli.xxx import`)
