# Ubo Application

## Run on Rasperry Pi

Fist make sure you have the system dependencies installed:

```sh
sudo apt install pip virtualenv
libmtdev libg1 libegl1 libcap-dev
python3-libcamera libzvar0 --no-install-recommends
```

You can install and run Ubo app on Raspberry Pi by setting a virtual environment and install the pip package:

```sh
virtualenv --system-site-packages ubo-app
source ubo-app/bin/activate
pip install ubo-app[default]
./ubo-app/bin/ubo
```

## Contribution

```sh
poetry install # You need `--extras=dev` if you want to run it on a non-raspberry machine
poetry run ubo
```

For headless development (must be on the same network), set the hostname `ubo-development-pod` to with the ip address or hostname (e.g. `ubo-xxx.local`) of the device in your network in `/etc/host` file.

Then run `poetry run poe deploy_to_device --deps` or simply `poe deploy_to_device --deps` if you virtualenv is active (`poetry shell`) whenever you want to run it on the device. Make sure you setup the virtualenv in `~/ubo-app` directory before running this command.

## Conventions

1. Use `UBO_` prefix for all environment variables, additional prefixes may come after `UBO_` as needed.
1. Always use frozen dataclasses for action and state classes.
1. Each `action` should have only two attributes: `type` and `payload`. Payload class of an action should also be a frozen dataclass with the same name as the action class with "Payload" prefix.
