# 🚀 Ubo App

[![PyPI version](https://img.shields.io/pypi/v/ubo-app.svg)](https://pypi.python.org/pypi/ubo-app)
[![License](https://img.shields.io/pypi/l/ubo-app.svg)](https://github.com/ubopod/ubo-app/LICENSE)
[![Python version](https://img.shields.io/pypi/pyversions/ubo-app.svg)](https://pypi.python.org/pypi/ubo-app)
[![Actions status](https://github.com/ubopod/ubo-app/workflows/CI/CD/badge.svg)](https://github.com/ubopod/ubo-app/actions)
[![codecov](https://codecov.io/gh/ubopod/ubo-app/graph/badge.svg?token=KUI1KRDDY0)](https://codecov.io/gh/ubopod/ubo-app)

## 🌟 Overview

Ubo App is a Python application for managing Raspberry Pi utilities and Ubo-specific features.

![Ubo Pod photo](https://github.com/ubopod/ubo-app/assets/94014876/9438ab51-9b40-46b8-a656-80b8fcb72bc)

Example screenshots:

![Ubo Pod photo](https://github.com/ubopod/ubo-app/assets/94014876/899d32e4-ef8e-4849-a967-1e21ad12297a)

## 🚧 Disclaimer

Be aware that at the moment, Ubo app sends crash reports to Sentry. Soon we will limit this to beta versions only.

## ⚙️ Notable Features

- Headless WiFi on-boarding with QR code
- Easy headless remote access with SSH and VS Code tunnel
- Install and run Docker apps headlessly
- Access and control basic RPi utilities and settings
- gRPC API for remote control - find sample clients [here](https://github.com/ubopod/ubo-grpc-clients)

## 📋 Requirements

Ubo app is developed to run on Raspberry Pi 4 and 5. The experience is optimized around Ubo Pod which offers

- a minimal LCD display and GUI with a keypad
- stereo microphone and speakers,
- camera
- LED ring
- sensors

The app functions even if some of these hardware elements are not provided, however some of the features that rely on these hardware components may not function. For example, WiFi onboarding with QR code requires a camera onboard.

## 📦 Installation

### Pre-packaged image

Ubo Pod ships with a pre-flashed MicroSD card that has the app installed on it by default.

If you don't have it, or you just want to set up a fresh device, then:

1. download one of the images from the release section
1. Use Raspberry Pi Images and choose `custom image` to provide the download image file.
1. Write to the image
1. Use the image to boot your Ubo Pod or Raspberry Pi

This is the fastest, easiest, and recommended way to get started with Ubo App.

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

##### Compiling the web application

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

You need to install dependencies with this command once:

```bash
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

## 🔒 License

This project is released under the Apache-2.0 License. See the [LICENSE](./LICENSE) file for more details.
