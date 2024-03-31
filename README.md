# 🚀 Ubo App

[![image](https://img.shields.io/pypi/v/ubo-app.svg)](https://pypi.python.org/pypi/ubo-app)
[![image](https://img.shields.io/pypi/l/ubo-app.svg)](https://github.com/ubopod/ubo-app/LICENSE)
[![image](https://img.shields.io/pypi/pyversions/ubo-app.svg)](https://pypi.python.org/pypi/ubo-app)
[![Actions status](https://github.com/ubopod/ubo-app/workflows/CI/CD/badge.svg)](https://github.com/ubopod/ubo-app/actions)
[![codecov](https://codecov.io/gh/ubopod/ubo-app/graph/badge.svg?token=KUI1KRDDY0)](https://codecov.io/gh/ubopod/ubo-app)

## 🌟 Overview

Ubo App is a Python application for managing Raspberry Pi utilities and UBo-specific
features.

## 🚧 Disclaimer

Be aware that at the moment, Ubo app sends crash reports to Sentry. Soon we will
limit this to beta versions only.

## ⚙️ Features

[To be written]

## 📋 Requirements

These things are already taken care of in the official Ubo Pod image, so if you are
botting from that image, you can ignore this section.

- Python 3.9 or later.
- Run `raspi-config` -> Interface Options -> Enable SPI

## 📦 Installation

Note that as part of the installation process, these debian packages are installed:

- build-essential
- git
- i2c-tools
- libcap-dev
- libegl1
- libgl1
- libmtdev1
- libsystemd-dev
- libzbar0
- python3
- python3-dev
- python3-libcamera
- python3-alsaaudio
- python3-picamera2
- python3-pip
- python3-pyaudio
- python3-virtualenv

Also be aware that ubo-app only installs in `/opt/ubo` and it is not customizable
at the moment.

---

⚠️ **Executing scripts directly from the internet with root privileges poses a significant
security risk. It's generally a good practice to ensure you understand the script's
content before running it. You can check the content of this particular script
[here](https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/install.sh)
before running it.**

---

To install ubo, run this command in a terminal shell:

```bash
curl -sSL https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/install.sh\
  | sudo bash
```

If you want to install docker service and configure ubo to be able to use it run
this:

```bash
curl -sSL https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/install.sh\
  | sudo WITH_DOCKER=true bash
```

To allow the installer to install the latest alpha version of ubo run this:

```bash
curl -sSL https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/install.sh\
  | sudo ALPHA=true bash
# or
curl -sSL https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/install.sh\
  | sudo ALPHA=true WITH_DOCKER=true bash
```

## 🤝 Contributing

Contributions following Python best practices are welcome.

### ℹ️️ Conventions

- Use `UBO_` prefix for environment variables.
- Use `ubo:` prefix for notification ids used in ubo core and `<service_name>:` prefix
  for notification ids used in services.
- Use `ubo:` prefix for icon ids used in ubo core and `<service_name>:` prefix for
  icon ids used in services.

## 🔒 License

This project is released under the Apache-2.0 License. See the [LICENSE](./LICENSE)
file for more details.
