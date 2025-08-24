# ☯️ Ubo App

[![PyPI version](https://img.shields.io/pypi/v/ubo-app.svg)](https://pypi.python.org/pypi/ubo-app)
[![License](https://img.shields.io/pypi/l/ubo-app.svg)](https://github.com/ubopod/ubo-app/LICENSE)
[![Python version](https://img.shields.io/pypi/pyversions/ubo-app.svg)](https://pypi.python.org/pypi/ubo-app)
[![Actions status](https://github.com/ubopod/ubo-app/workflows/CI/CD/badge.svg)](https://github.com/ubopod/ubo-app/actions)
[![codecov](https://codecov.io/gh/ubopod/ubo-app/graph/badge.svg?token=KUI1KRDDY0)](https://codecov.io/gh/ubopod/ubo-app)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ubopod/ubo_app)

## 📑 Table of Contents

- [🌟 Overview](#🌟-overview)
- [🚧 Disclaimer](#🚧-disclaimer)
- [⚙️ Notable Features](#⚙️-notable-features)
- [📋 Requirements](#📋-requirements)
- [🪏 Installation](#🪏-installation)
  - [Pre-packaged image](#pre-packaged-image)
  - [Install on existing OS](#install-on-existing-os)
- [🤝 Contributing](#🤝-contributing)
  - [ℹ️️ Conventions](#ℹ️️-conventions)
  - [Development](#development)
- [🛠️ Hardware](#🛠️-hardware)
  - [Emulation](#emulation)
  - [Ubo Pod](#ubo-pod)
  - [DIY Path](#diy-path)
- [🏗️ Architecture](#🏗️-architecture)
- [📦 Notable dependencies](#📦-notable-dependencies)
- [🗺️ Roadmap](#🗺️-roadmap)
- [🔒 License](#🔒-license)

## 🌟 Overview

Ubo App is a Python application that provides a unified interface and tools for developing and running hardware-integrated apps. 

It offers a minimalistic, yet intuitive UI for end-users to install and interact with developer apps. It is optimized for Raspberry Pi (4 & 5) devices. 

Hardware specific capabilities such as infrared send/receive, sensing, LED ring, etc. are supported by Ubo Pod hardware. 

It is also possible to DIY your own hardware, see the [hardware DIY section](#diy-path) below.

### Goals

The design is centered around the following goals:

  - Making hardware-integarted app development easier 
  - Offer no-code/no-terminal UI/UX optionsto both developers and end-users of their apps
  - Give developers tools to build apps with multi-modal UX
  - Leverage tight hardware and software co-development to unlock new potentials
  - Let users focus on their app logic while Ubo app handles the rest (hardware abstractions, UI, etc.)
  - Hot-pluggable services
  - Modular and friendly to AI tool-calling
  - Remote API access (gRPC)

⚠️ Due to limited development resources, we are not able to support every single board computer (SBC), operating system, and hardware configuration. 

If you are willing to supporting other SBCs or operating systems, please consider contributing to the project.

<b>Example GUI screenshots</b>

![GUI Overview](https://raw.githubusercontent.com/ubopod/mediakit/main/images/gui-overview.png))

## 🚧 Disclaimer

Be aware that at the moment, Ubo app sends crash reports to Sentry. Soon we will limit this to beta versions only.

## ⚙️ Notable Features

- Easy WiFi on-boarding with QR code or hotspot  
- Headless (no monitor/keyboard) remote access setup 
    - SSH
    - VS Code tunnel
    - Raspberry Pi Connect
- Install and run Dockerized apps headlessly
- One-click install for pre-configured apps
- Access and control basic Linux utilities and settings
  - User management
  - Network management
  - File system operations
- Natural language interactions for tool calling (voice AI) (experimental)
- Web UI
- Infrared remote control (send/receive)
- gRPC API for remote control - find sample clients [here](https://github.com/ubopod/ubo-grpc-clients)

Check [roadmap section](#🗺️-roadmap) below for upcoming features.

## 📋 Requirements

At minimum you need a Raspberry Pi 4 or 5 to run Ubo App. 

To run LLM models locally, we recommend a Raspberry Pi 5 with at least 8GB of RAM.

For features that require add-on hardware that is not natively supported by Raspberry Pi (such as audio, infrared rx/tx, sensors, etc), you can:

1. Purchase an Ubo Pod Development Kit 
2. DIY the hardware
3. Use only subset of hardware features emulated in the browser

For more details check out the [hardware section](#🛠️-hardware) below.

🙏 Please consider supporting this project by pre-ordering an Ubo Pod Dev Edition on [Kickstarter](https://www.kickstarter.com/projects/ubopod/ubo-pod-dev-edition). 

The sales proceeds from the hardware will be used to support continued development and maintenance of Ubo App and its open source dependencies.

<b> Note </b>: 
The app still functions even if some special hardware elements (audio, infrared rx/tx, sensors, etc) are not provided. The features that rely on these hardware components just won't function. For example, WiFi onboarding with QR code requires a camera onboard. 

## 🪏 Installation

### Pre-packaged image

Ubo Pod ships with a pre-flashed MicroSD card that has the app installed on it by default.

If you don't have it, or you just want to set up a fresh device, then:

1. Download one of the images from the release section
1. Use Raspberry Pi Images and choose `custom image` to provide the download image file.
1. Write to the image
1. Use the image to boot your Ubo Pod or Raspberry Pi

This is the fastest, easiest, and recommended way to get started with Ubo App. 

🙋‍♂️If this is the first time you are flashing an image for Raspberry Pi, I recommend following the more detailed steps [here](https://github.com/ubopod/ubo-image).

To run the app on bare Raspberry Pi, you can watch this short [demo video](https://www.youtube.com/watch?v=Rro3YLVIUx4).

### Install on existing OS

If you want to install the image on an existing operating system, then read on. Otherwise, skip this section.

---

⚠️ **Executing scripts directly from the internet with root privileges poses a significant security risk. It's generally a good practice to ensure you understand the script's content before running it. You can check the content of this particular script [here](https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/install.sh) before running it.**

---

To install ubo, run this command in a terminal shell:

```bash
curl -sSL https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/scripts/install.sh | sudo bash
```

If you don't want to install docker service you can set the `WITH_DOCKER` environment variable to `false`:

```bash
curl -sSL https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/scripts/install.sh | sudo WITHOUT_DOCKER=true bash
```

To install a specific version of ubo, you can set the `TARGET_VERSION` environment variable to the desired version:

```bash
curl -sSL https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/scripts/install.sh | sudo TARGET_VERSION=0.0.1 bash
```

Note that as part of the installation process, these debian packages are installed:

- accountsservice
- dhcpcd
- dnsmasq
- git
- hostapd
- i2c-tools
- ir-keytable
- libasound2-dev
- libcap-dev
- libegl1
- libgl1
- libmtdev1
- libzbar0
- python3-alsaaudio
- python3-apt
- python3-dev
- python3-gpiozero
- python3-libcamera
- python3-picamera2
- python3-pip
- python3-virtualenv
- rpi-lgpio

Also be aware that ubo-app only installs in `/opt/ubo` and it is not customizable
at the moment.

## 🤝 Contributing

Contributions following Python best practices are welcome.

### ℹ️️ Conventions

- Use `UBO_` prefix for environment variables.
- Use `ubo:` prefix for notification ids used in ubo core and `<service_name>:` prefix for notification ids used in services.
- Use `ubo:` prefix for icon ids used in ubo core and `<service_name>:` prefix for icon ids used in services.

### Development

#### Setting up the development environment

To set up the development environment, you need to [have `uv` installed](https://docs.astral.sh/uv/).

First, clone the repository (you need to have [git-lfs installed](https://docs.github.com/en/repositories/working-with-files/managing-large-files/installing-git-large-file-storage)):

```bash
git clone https://github.com/ubopod/ubo_app.git
git lfs install
git lfs pull
```

In environments where some python packages are installed system-wide, like Raspberry Pi OS, you need to run the following command to create a virtual environment with system site packages enabled:

```bash
uv venv --system-site-packages
```

Then, navigate to the project directory and install the dependencies:

```bash
uv sync --dev
```

Now you can run the app with:

```bash
HEADLESS_KIVY_DEBUG=true uv run ubo
```

#### Run the app on the physical device

Add `ubo-development-pod` host in your ssh config at `~/.ssh/config`:

```plaintext
Host ubo-development-pod
  HostName <ubopod IP here>
  User pi
```

⚠️*Note: You may want to add the ssh public key to the device's authorized keys (`~/.ssh/authorized_keys`) so that you don't need to enter the password each time you ssh into the device. If you decide to use password instead,  you need to reset the password for Pi user first using the GUI on the device by going to Hamburger Menu -> Settings -> System -> Users and select pi user*

Before you deploy the code onto the pod, you have to run the following command to generate the protobuf files and compile the web application.

##### Generating the protobuf files

Please make sure you have [buf](https://github.com/bufbuild/buf) library installed locally. If you are developing on a Mac or Linux, you can install it using Homebrew:

```bash
brew install bufbuild/buf/buf
```

Then, run the following command to generate the protobuf files whenever an action or

```bash
uv run poe proto
```

This is a shortcut for running the following commands:

```bash
uv run poe proto:generate # generate the protobuf files based on the actions/events defined in python files
uv run poe proto:compile  # compile the protobuf files to python files
```

##### Building the web application

If you are running it for the firt time, you first need to install the dependencies for the web application:

```bash
cd ubo_app/services/090-web-ui/web-app
npm install # Only needed the first time or when dependencies change
```

Then, you need to compile the protobuf files and build the web application:

```bash
cd ubo_app/services/090-web-ui/web-app
npm run proto:compile
npm run build
```

If you are modifying web-app typescript files, run `npm run build:watch` and let it stay running in a terminal. This way, whenever you modify web-app files, it will automatically update the built files in `dist` directory as long as it’s running.

If you ever add, modify or remove an action or an event you need to run `poe proto` and `npm run proto:compile` again manually.

---

Then you need to run this command once to set up the pod for development:

```bash
uv run poe device:deploy:complete
```

After that, you can deploy the app to the device with:

```bash
uv run poe device:deploy
```

To run the app on the device, you can use either of these commands:

```bash
uv run poe device:deploy:restart # gracefully restart the app with systemctl
uv run poe device:deploy:kill    # kill the process, which will be restarted by systemd if the service is not stopped
```

#### Running tests on desktop

Easiest way to run tests is to use the provided `Dockerfile`s. To run the tests in a container, you first need to create the development images by running:

```bash
uv run poe build-docker-images
```

Then you can run the tests with:

```bash
docker run --rm -it --name ubo-app-test -v .:/ubo-app -v ubo-app-dev-uv-cache:/root/.cache/uv ubo-app-test
```

You can add arguments to the `pytest` command to run specific tests like this:

```bash
docker run --rm -it --name ubo-app-test -v .:/ubo-app -v ubo-app-dev-uv-cache:/root/.cache/uv ubo-app-test -- <pytest-args>
```

For example, to run only the tests in the `tests/integration/test_core.py` file, you can run:

```bash
docker run --rm -it -v .:/ubo-app -v ubo-app-dev-uv-cache:/root/.cache/uv -v uvo-app-dev-uv-local:/root/.local/share/uv -v ubo-app-dev-uv-venv:/ubo-app/.venv ubo-app-test
```

To pass it command line options add a double-dash before the options:

```bash
docker run --rm -it -v .:/ubo-app -v ubo-app-dev-uv-cache:/root/.cache/uv -v uvo-app-dev-uv-local:/root/.local/share/uv -v ubo-app-dev-uv-venv:/ubo-app/.venv ubo-app-test -- -svv --make-screenshots --override-store-snapshots --override-window-snapshots
```

You can also run the tests in your local environment by running:

```bash
uv run poe test
```

⚠️**Note:** When running the tests in your local environment, the window snapshots produced by tests may mismatch the expected snapshots. This is because the snapshots are taken with a certain DPI and some environments may have different DPI settings. For example, we are aware that the snapshots taken in macOS have different DPI settings. If you encounter this issue, you should run the tests in a Docker container as described above.

#### Running tests on the device

You need to install dependencies with following commands once:

```bash
uv run poe device:test:copy
uv run poe device:test:deps
```

Then you can use the following command each time you want to run the tests:

```bash
uv run poe device:test
```

#### Running linter

To run the linter run the following command:

```bash
uv run poe lint
```

To automatically fix the linting issues run:

```bash
uv run poe lint --fix
```

#### Running type checker

To run the type checker run the following command on the pod:

```bash
uv run poe typecheck
```

⚠️*Note: Please note typecheck needs all packages to be present. To run the above command on the pod, you need to clone the ubo-app repository on the pod, apply your changes on it, have uv installed on the pod and install the dependencies.*

If you prefer to run typecheck on the local machine, clone [stubs repository](https://github.com/ubopod/ubo-non-rpi-stubs) (which includes typing stubs for third-party packages) and place the files under `typings` directory. Then run `poe typecheck` command.

#### Adding new services

It is not documented at the moment, but you can see examples in `ubo_app/services` directory.

⚠️*Note: To make sure your async tasks are running in your service's event loop and not in the main event loop, you should use the `create_task` function imported from `ubo_app.utils.async_` to create a new task. Using `await` inside `async` functions is always fine and doesn't need any special attention.*

⚠️*Note: Your service's setup function, if async, should finish at some point, this is needed so that ubo can know the service has finished its initialization and ready to be used. So it should not run forever, by having a loop at the end, or awaiting an ongoing async function or similar patterns. Running a never-ending async function using `create_task` imported from `ubo_app.utils.async_` is alright.

#### QR code

In development environment, the camera is probably not working, as it is relying on `picamera2`, so it may become challenging to test the flows relying on QR code input.

To address this, the camera module, in not-RPi environments, will try reading from `/tmp/qrcode_input.txt` and `/tmp/qrcode_input.png` too. So, whenever you encounter a QR code input, you can write the content of the QR code in the text file path or put the qrcode image itself in the image file path and the application will read it from there and continue the flow.

Alternatively you may be able to provide the input in the web-ui (needs refresh at the moment) or provide it by `InputProvideAction` in grpc channel.

## 🛠️ Hardware 

This section presents different hardware or emulation options that you can use with Ubo app.

### Emulation

To remove barriers to adoption as much as possible and allow developers use Ubo app without hardware depenencies, we are currently emulating the physical GUI in the browser. 

The audio playback is also streamed through the broswer. 

We plan to emulate camera and microphone with WebRTC in the future.

![Ubo Pod photo](https://raw.githubusercontent.com/ubopod/mediakit/main/images//gui_emulation.png)

However, other specialized hardware components (sensors, infrared rx/tx, etc) cannot be emulated. 

### Ubo Pod

![Ubo Pod photo](https://raw.githubusercontent.com/ubopod/mediakit/main/images/rotating-pod.gif)

Ubo pod is an open hardware that includes the following additional hardware capabilities that is supported by Ubo app out of the box:

- A built-in minimal GUI (color LCD display and keypad)
- Stereo microphone and speakers (2W)
- Camera (5MP)
- LED ring (27 addressable RGB LEDs)
- Sensors
   - Ambient light sensor
   - Temperature sensor
   - STEMMA QT / Qwiic connector for additional sensors
- Infrared
  - Receiver (wideband)
  - Transmitter (4 high power LEDs)
- 2 full HDMI ports
- Power/reset button 
- NVMe storage (Pi 5 only)

For more information on hardware spec, see the website [getubo.com](https://getubo.com).

This is an open hardware. You can access mechanical design files [here](https://github.com/ubopod/ubo-mechanical) and electrical design files [here](https://github.com/ubopod/ubo-pcb).

### DIY path

You can also buy different HATs from different vendors to DIY the hardware. Future plans include supporting USB microphone, speakers, cameras as well with headless setup.

This however involves having to purchase multiple HATs from different vendors and the process may not be the easiest and most frictionless. You may have to dig into the code and make some small changes to certain setups and configurations.

I made the table below that shows options for audio, cameras, and other sub-components:

| Function | Options |
| --- | --- |
| Audio | [Respeaker 2-Mic Audio HAT](https://www.seeedstudio.com/ReSpeaker-2-Mics-Pi-HAT.html), [Adafruit Voice Bonnet](https://www.adafruit.com/product/4757), [Waveshare WM8960 Hat](https://www.waveshare.com/wm8960-audio-hat.htm), [Adafruit BrainCraft HAT](https://www.adafruit.com/product/4374) |
| Speakers | [1 or 2W, 8 Ohm](https://www.adafruit.com/product/1669) |
| Camera | Raspberry Pi Camera Modules V1.3, [V2](https://www.raspberrypi.com/products/camera-module-v2/), or [V3](https://www.raspberrypi.com/products/camera-module-3/) |
| LCD (also emulated in the browser) | [240x240 TFT Display](https://www.adafruit.com/product/4421), [Adafruit BrainCraft HAT](https://www.adafruit.com/product/4374) |
| Keypad | [AW9523 GPIO Expander](https://www.adafruit.com/product/4886) |
| LED ring | [Neopixel LED ring](https://www.adafruit.com/product/1586) |
| Ambient Light Sensor | [VEML7700 Lux Sensor](https://www.adafruit.com/product/4162) |
| Temperature Sensor | [PCT2075 Temperature Sensor](https://www.adafruit.com/product/4369) |

## 🏗️ Architecture

The architecture is fundamentally event-driven and reactive, built around a centralized Redux store that coordinates all system interactions through immutable state updates and event dispatching. 

Services communicate exclusively through Redux actions and events rather than direct method calls, with each service running in its own isolated thread while subscribing to relevant state changes and events. 

The system uses custom event handlers that automatically route events to the appropriate service threads, enabling reactive responses to state changes across hardware interfaces, user interactions, and system events.  

This reactive architecture allows components like the web UI to subscribe to display render events and audio playback events in real-time, creating a responsive system where changes propagate automatically through the event stream without tight coupling between components.

![Software architecture](https://raw.githubusercontent.com/ubopod/mediakit/main/images/architecture.jpg)

The following is a summary of key architecture components.

-  <b>Redux-Based State Management</b>: Central `UboStore` manages all application state through immutable state trees, with each service contributing its own state slice (audio, camera, display, docker, wifi, etc.) and communicating via actions and events.

-  <b>Modular Service Architecture</b>: 21+ core services run in isolated threads with dedicated event loops, organized by priority (`000-0xx` for hardware, `030-0xx` for networking, `080-0xx` for applications, `090-0xx` for UI), each with their own setup.py, reducer.py, and ubo_handle.py files.

-  <b>Hardware Abstraction Layer</b>: Comprehensive abstraction for Raspberry Pi components (ST7789 LCD, WM8960 audio, GPIO keypad, sensors, camera, RGB ring) with automatic environment detection and mock implementations for development on non-RPi systems.

-  <b>Multi-Interface Access</b>: Supports web browser access (port 4321), gRPC API (port 50051), SSH access, and direct hardware interaction, with a web UI service providing hotspot configuration and dashboard functionality.

-  <b>System Integration</b>: Integrates with `systemd` and `d-bus` for service management, Docker for container runtime, and `NetworkManager` for network configuration, with a separate system manager process handling root-privilege operations via Unix sockets.

<b>Notes:</b>  

The application follows a structured initialization sequence through `ubo_app/main.py` and uses the `uv` package manager for dependency management. 

The architecture supports both production deployment on Raspberry Pi devices and development environments with comprehensive mocking systems, making it suitable for cross-platform development while maintaining hardware-specific capabilities.

DeepWiki pages you might want to explore:

- [Overview](https://deepwiki.com/ubopod/ubo_app/1-overview)
- [Architecture](https://deepwiki.com/ubopod/ubo_app/2-architecture)

## Notable dependencies

Here are the key dependencies organized by category:

### Core Framework & State Management

- `python-redux`: Redux-based state management system for the entire app
- `ubo-gui`: Custom GUI framework built on Kivy for the user interface
- `headless-kivy`: Headless Kivy implementation for supporting LCD display over SPI

### Hardware Control (Raspberry Pi)

- `adafruit-circuitpython-rgb-display`: ST7789 LCD display driver
- `adafruit-circuitpython-neopixel`: RGB LED ring control
- `adafruit-circuitpython-aw9523`: I2C GPIO expander for keypad
- `adafruit-circuitpython-pct2075`: Temperature sensor driver
- `adafruit-circuitpython-veml7700`: Light sensor driver
- `rpi-lgpio`: Low-level GPIO access for Raspberry Pi
- `gpiozero`: GPIO abstraction layer
- `rpi-ws281x`: WS281x LED strip control library
- `pyalsaaudio`: ALSA audio interface for Linux audio control
- `pulsectl`: PulseAudio control for audio management
- `simpleaudio`: Simple audio playback functionality

### Voice AI

- `piper-tts`: Text-to-speech synthesis engine
- `vosk`: Speech recognition library
- `pvorca`: Picovoice Text-to-speech synthesis engine
- `pipecat-ai`: framework for building real-time voice and multimodal conversational agents

### Networking & Services

- `aiohttp`: Async HTTP client/server for web services
- `quart`: Async web framework for the web UI service
- `sdbus-networkmanager`: NetworkManager D-Bus interface for WiFi
- `netifaces`: Network interface enumeration
- `docker`: Docker API client for container management

### QR Codes

- `pyzbar`: QR code and barcode scanning library

### System Utilities

- `psutil`: System and process monitoring utilities
- `platformdirs`: Platform-specific directory paths
- `tenacity`: Retry logic and error handling
- `fasteners`: File locking and synchronization

### Development Environment Abstraction

- `python-fake`: Mock hardware components for development

### gRPC Communication

- `betterproto`: Protocol buffer compiler and runtime

<b>Notes:</b>
The project uses platform-specific dependencies with markers like `platform_machine=='aarch64'` for Raspberry Pi-specific libraries and `sys_platform=='linux'` for Linux-only components. The python-fake library enables development on non-Raspberry Pi systems by providing mock implementations of hardware components.

## 🗺️ Roadmap

This is a tentative roadmap for future features. It is subject to change.

- Emulation for camera and microphone inside browser (requires SSL certificate for browser permissions)
- Allow users to pick their soundcard for play and record via GUI (e.g. USB audio)
- Allow users to pick their camera for video via GUI (e.g. USB camera)
- Option to turn Ubo pod into a voice satellite with wyoming protocol with Home Assistant
- Make all on-board sensors and infrared discoverable and accessible by Home Assistant
- Let users record Infrared signals and assign them to trigger custom actions
- Expose `pipecat-ai` preset pipeline configuration via GUI
- Support for Debian Trixie (13)

If you have any suggestions or feature requests, please open a discussion [here](https://github.com/ubopod/ubo_app/discussions).

## 🔒 License

This project is released under the Apache-2.0 License. See the [LICENSE](./LICENSE) file for more details.
