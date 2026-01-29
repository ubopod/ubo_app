# Ubo TUI Client

A Text User Interface for Ubo App that communicates via gRPC.

## Installation

```bash
cd ubo_app/tui
uv sync
```

## Usage

```bash
# Ensure ubo_app is running with gRPC server enabled
uv run ubo-tui --host localhost --port 50051
```

## Controls

| Key | Action |
|-----|--------|
| **Up/Down Arrow** | Scroll menu (or adjust volume on home screen) |
| **Enter** | Select current item |
| **1/2/3** | Select item by position |
| **Escape/Backspace** | Go back |
| **h** | Go to home screen |
| **q** | Quit |

## Architecture

The TUI acts as a "dumb UI" client that:

1. **Subscribes** to `ViewChangedEvent` via gRPC to receive view updates
2. **Renders** the view data as text-based UI using Textual
3. **Dispatches** user input as Redux actions via gRPC

This mirrors the behavior of the main Kivy GUI but runs in any terminal.

## Requirements

- Python 3.11+
- Running ubo_app instance with gRPC server enabled
- Terminal with Unicode support (for icons)
