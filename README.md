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
- Install these packages:

  ```sh
  sudo apt install pip virtualenv libmtdev libgl1 libegl1 libcap-dev \
       python3-libcamera libzbar0 --no-install-recommends
  ```

## 📦 Installation

```bash
virtualenv --system-site-packages ubo-app
source ubo-app/bin/activate
pip install ubo-app
# Run this if you want to run it automatically when RPi boots
sudo ubo-app/bin/ubo install_service
```

## 🤝 Contributing

Contributions following Python best practices are welcome.

### ⚠️ Important Notes

- Use `Ubo_` prefix for environment variables.

## 🔒 License

This project is released under the Apache-2.0 License. See the [LICENSE](./LICENSE)
file for more details.
