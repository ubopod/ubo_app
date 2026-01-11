# Ubo App - AI Assistant Context

This document provides context for AI assistants working with the Ubo App codebase.

## Project Overview

Ubo App is a Python application that provides a unified interface and tools for developing and running hardware-integrated apps, optimized for Raspberry Pi (4 & 5) devices. It offers a minimalistic, intuitive UI for end-users to install and interact with developer apps.

**Key characteristics:**
- Event-driven and reactive architecture built around Redux
- Modular service-based design
- Hardware abstraction layer for Raspberry Pi components
- Multi-interface access (web UI, gRPC API, SSH, direct hardware)
- Cross-platform development support (works on desktop with mocks)

## Architecture

### Redux-Based State Management
- Central `UboStore` manages all application state through immutable state trees
- Each service contributes its own state slice
- Communication happens exclusively via Redux actions and events (no direct method calls)
- Custom event handlers automatically route events to appropriate service threads

### Service Architecture
- 21+ core services run in isolated threads with dedicated event loops
- Services are organized by priority:
  - `000-0xx`: Hardware services (audio, display, keypad, RGB ring, sensors, camera)
  - `030-0xx`: Networking services (WiFi, Ethernet, IP)
  - `050-0xx`: System services (SSH, users, VS Code, LightDM, RPI Connect)
  - `080-0xx`: Application services (Docker)
  - `090-0xx`: UI/Interface services (web-ui, assistant, file-system, infrared, speech-recognition)
- Each service typically has: `setup.py`, `reducer.py`, `ubo_handle.py`

### Hardware Abstraction
- Comprehensive abstraction for Raspberry Pi components
- Automatic environment detection
- Mock implementations for development on non-RPi systems
- Hardware-specific dependencies use platform markers (e.g., `platform_machine=='aarch64'`)

## Technology Stack

**Core:**
- Python 3.11 (strict requirement: >=3.11, <3.12)
- `python-redux==0.24.0` (pinned) for state management
- `ubo-gui` built on Kivy for UI
- `headless-kivy` for LCD display over SPI

**Hardware (Raspberry Pi):**
- Adafruit CircuitPython libraries for sensors and peripherals
- `rpi-lgpio`, `gpiozero` for GPIO control
- `pyalsaaudio`, `pulsectl` for audio
- `picamera2` for camera

**Networking & Services:**
- `aiohttp`, `quart` for async web services
- `sdbus-networkmanager` for WiFi management
- `docker` for container management
- `betterproto` for gRPC/protobuf

**Voice AI:**
- `piper-tts`, `pvorca` for text-to-speech
- `vosk` for speech recognition
- `pipecat-ai` for real-time voice agents

## Development Environment

### Setup
```bash
# Install uv package manager first
git clone https://github.com/ubopod/ubo_app.git
git lfs install && git lfs pull
uv venv --system-site-packages  # On Raspberry Pi OS
uv sync --dev
```

### Key Commands (via poethepoet)
```bash
uv run poe proto              # Generate and compile protobuf files
uv run poe lint               # Run ruff linter
uv run poe lint --fix         # Auto-fix linting issues
uv run poe typecheck          # Run pyright type checker
uv run poe test               # Run pytest tests
uv run poe build-docker-images # Build dev/test Docker images
```

### Development Workflow
1. **Generate protobuf files** when actions/events change:
   ```bash
   uv run poe proto
   ```

2. **Build web application** (first time or when dependencies change):
   ```bash
   cd ubo_app/services/090-web-ui/web-app
   npm install
   npm run proto:compile
   npm run build
   # Or use: npm run build:watch (for auto-rebuild during development)
   ```

3. **Deploy to device** (requires SSH config for `ubo-development-pod`):
   ```bash
   uv run poe device:deploy:complete  # First time setup
   uv run poe device:deploy           # Regular deployment
   uv run poe device:deploy:restart   # Restart service
   ```

4. **Run locally** (headless mode):
   ```bash
   HEADLESS_KIVY_DEBUG=true uv run ubo
   ```

### Testing
- **Docker (recommended for desktop):**
  ```bash
  uv run poe build-docker-images
  docker run --rm -it -v .:/ubo-app -v ubo-app-dev-uv-cache:/root/.cache/uv ubo-app-test
  ```
- **Local:** `uv run poe test`
- **On device:** `uv run poe device:test`

## Code Conventions

### Environment Variables
- Use `UBO_` prefix for all Ubo-specific environment variables

### Notification IDs
- Use `ubo:` prefix for core notifications
- Use `<service_name>:` prefix for service-specific notifications

### Icon IDs
- Use `ubo:` prefix for core icons
- Use `<service_name>:` prefix for service-specific icons

### Async Task Management
- **ALWAYS** use `create_task` from `ubo_app.utils.async_` for async tasks
- This ensures tasks run in the service's event loop, not the main loop
- Using `await` inside async functions is always fine

### Service Setup Functions
- Setup functions (if async) must finish at some point
- Don't run forever with loops or await ongoing functions
- Use `create_task` for never-ending async operations

## File Structure

```
ubo_app/
├── main.py                 # Application entry point
├── store/                  # Redux store and state definitions
├── services/               # Modular services (see architecture above)
│   ├── 000-audio/
│   ├── 000-display/
│   ├── 000-keypad/
│   ├── 030-wifi/
│   ├── 080-docker/
│   ├── 090-web-ui/
│   └── ...
├── system/                 # System-level utilities and managers
├── rpc/                    # gRPC/protobuf definitions and generated code
└── utils/                  # Shared utilities

tests/
├── integration/            # Integration tests
├── flows/                  # Flow tests
├── store/                  # Store tests
└── fixtures/               # Test fixtures

scripts/                    # Build and deployment scripts
```

## Important Notes for AI Assistants

### When Making Changes

1. **Read files before editing:** NEVER propose changes to code you haven't read
2. **Prefer editing over creating:** ALWAYS prefer editing existing files to creating new ones
3. **Avoid over-engineering:**
   - Only make changes that are directly requested or clearly necessary
   - Don't add features, refactoring, or "improvements" beyond what was asked
   - Don't add comments, docstrings, or type annotations to code you didn't change
   - Don't add error handling for scenarios that can't happen
   - Three similar lines of code is better than a premature abstraction

4. **Security:** Be careful not to introduce vulnerabilities (command injection, XSS, SQL injection, etc.)

5. **Protobuf workflow:** When actions/events change:
   - Run `uv run poe proto:generate` to regenerate proto files
   - Run `uv run poe proto:compile` to compile them
   - If web-app is affected, run `npm run proto:compile` in web-app directory

6. **Service development:**
   - Services communicate only via Redux actions/events
   - Each service runs in its own thread
   - Use `create_task` from `ubo_app.utils.async_` for background tasks

### Testing Environment

- **QR code input in development:** Write to `/tmp/qrcode_input.txt` or `/tmp/qrcode_input.png`
- **Window snapshots:** Run tests in Docker to avoid DPI mismatch issues on macOS
- **Type checking:** Best run on the actual device (pod) or with stubs from [ubo-non-rpi-stubs](https://github.com/ubopod/ubo-non-rpi-stubs)

### Deployment

- App installs to `/opt/ubo` (not customizable)
- Uses systemd for service management
- Separate system manager process handles root-privilege operations via Unix sockets
- Web UI available on port 4321
- gRPC API available on port 50051

## Resources

- **Main repo:** https://github.com/ubopod/ubo_app
- **Hardware (mechanical):** https://github.com/ubopod/ubo-mechanical
- **Hardware (electrical):** https://github.com/ubopod/ubo-pcb
- **Pre-packaged image:** https://github.com/ubopod/ubo-image
- **gRPC clients:** https://github.com/ubopod/ubo-grpc-clients
- **Website:** https://getubo.com
- **DeepWiki:**
  - [Overview](https://deepwiki.com/ubopod/ubo_app/1-overview)
  - [Architecture](https://deepwiki.com/ubopod/ubo_app/2-architecture)

## Current Branch

Branch: `display-timeout` (based on `main`)

Untracked files in working directory:
- log-ui.txt
- pi4-logs-2.txt
- pi4-logs-3.txt
- ubo_app/store/pi4-logs-4.txt
