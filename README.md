# 🚀 Ubo App

## 🌟 Overview

Ubo App is a Python application for managing Raspberry Pi utilities and UBo-specific
features.

## ⚙️ Features

[To be written]

## 📋 Requirements

These things are already taken care of in the official Ubo Pod image, so if you are
botting from that image, you can ignore this section.

- Python 3.9 or later.
- Run `raspi-config` -> Interface Options -> Enable SPI

## 📦 Installation

Note that as part of the installation process, these debian packages are installed:

- pip
- virtualenv
- libmtdev1
- libgl1
- libegl1
- libcap-dev
- python3-libcamera
- python3-alsaaudio
- python3-pyaudio
- libzbar0

Also be aware that ubo-app only installs in `/opt/ubo` and it is not customizable
at the moment.

---

⚠️ **Executing scripts directly from the internet with root privileges poses a significant
security risk. It's generally a good practice to ensure you understand the script's
content before running it.**

---

To install ubo, run this command in a terminal shell:

```bash
curl -sSL https://raw.githubusercontent.com/ubopod/ubo-app/main/ubo_app/system/install.sh | sudo bash
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
