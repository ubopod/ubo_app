# Changelog

## Version 0.11.1

- chore(test): set up testing framework with initial examples
- chore(test): set up snapshot test helper to compare screenshots of different stages
  of tests with previous successful tests using hashes

## Version 0.11.0

- feat: add ollama and open-webui docker images
- feat: render a qrcode for each ip x port combination of a container
- feat: add `UBO_DOCKER_PREFIX` to help pull docker images from local registries
  during development
- feat: let images depend on eachother's ip address to let semi composition
- feat: read the state of all relevant containers during initialization and update
  the store accordingly
- feat: add `--restart=always` for all containers, in the future we will make it
  customizable.
- chore: add python-dotenv and read `.env` and `.dev.env` files during initialization
- chore: update to latest version of ubo-gui and headless-kivy-pi

## Version 0.10.7

- chore: split asset files bigger than 2GB in the release into chunks of 2GB.
- refactor: general housekeeping

## Version 0.10.6

- fix: wireless module now has sufficient privileges

## Version 0.10.5

- chore: setup git-lfs for audio files

## Version 0.10.2

- chore: create ubo images for main branch based on lite, default and full versions
  of raspberry os in GitHub workflow
- chore: create GitHub release for main branch in GitHub workflows

## Version 0.10.1

- chore: GitHub workflow to publish pushes on `main` branch to PyPI

## Version 0.10.0

- chore: add integration GitHub workflow to check lint, typing and build issues
- refactor: address all lint issues and typing issues

## Version 0.9.9

- feat: add `monitor_unit` utility function to monitor status changes of systemd
  units
- refactor: make docker service mostly event-driven

## Version 0.9.8

- hotfix: wait for lingering process to finish and retry usreland `systemctl --user
daemon-reload` if needed
- hotfix: the `install_docker.sh` script now runs if an optional flag is set for
  bootstrap command

## Version 0.9.7

- fix: audio for when pipewire is installed
- fix: set permission for ubo user to disconnect wifi connections
- refactor: setup ubo as a lingering user and migrate ubo-app service from a system
  wide service to ubo userland service still starting after boot
- feature: ability to customize installation process with environment variables:
  - UPDATE: used for when ubo is installed and it should be updated to the latest
    version
  - ALPHA: installs latest version, even if it's an alpha version
  - WITH_DOCKER: installs docker service

## Version 0.9.6

- feat: add socket connection (volume bind) for portainer

## Version 0.9.5

- feat: expose all ports of containers and show the ports in a sub menu
- feat: option to remove a container without removing its image

## Version 0.9.4

- hotfix: provide `$USERNAME` environment variable for `install_docker.sh` script

## Version 0.9.3

- hotfix: postpone adding `ubo` to `docker` group for when `docker` is installed

## Version 0.9.2

- refactor: upgrade `ubo-led` service `ubo-system` service as a general service to
  take care of system tasks needing root access
- feat: use `ubo-system` to install and run docker service
- chore: add `--bootstrap` option to `deploy` script, it basically runs `ubo bootstrap`

## Version 0.9.1

- fix: load a module from nested packages into nested packages

## Version 0.9.0

- feat: add docker service to manage docker images/containers
- feat: add `UBO_LOGLEVEL` and `UBO_GUI_LOGLEVEL` environment variables
- feat: add `run_in_executor` to run non-coroutine (non-async) blocking functions
  without blocking the ui

## Version 0.8.9

- fix: modules loaded in services now get executed only once, avoiding registration
  of redundant subscriptions and listeners

## Version 0.8.8

- hotfix: remove a dangling whitespace in `install.sh`

## Version 0.8.7

- feat: add `ubo-pulseaudio.service` to take care of keeping pulseaudio up
- refactor: make sound service work with or without pulseaudio installed
- refactor: organize system related codes and assets

## Version 0.8.6

- fix: enable i2c and spi using `raspi-config` in `install.sh`
- fix: reboot after installation (needed for audio driver)
- fix: add user to netdev group in `install.sh`
- fix: install `python3-picamera2` and `python3-dev` debian packages in `install.sh`
- fix: blank screen when app is closing due to external signals
- fix: improve polkit rule to let user do wifi scan

## Version 0.8.5

- feat: add `sensors` service with temperature and light
- feat: show temperature and light values in the footer
- refactor: organize order of loading of services

## Version 0.8.4

- refactor: housekeeping - better organize `/ubo_app/store` in directories
- feat: automatically run update check whenever about menu is opened with a throttling
  of 10 seconds

## Version 0.8.3

- feat: introduce notification ids as a means to avoid duplicated notifications
- fix: don't show expired notifications
- feat: add a convention for notification ids and status icon ids in `README.me`

## Version 0.8.2

- feat: blank screen when turning off the device, as backlight has a pull up and
  turns on after devices is turned off

## Version 0.8.1

- feat: power off button now turns off the screen and actually powers off the device

## Version 0.8.0

- feat: update menu showing current version and a button to update ubo-app
- feat: add update system service to automatically install an update in boot time
  if it is already downloaded
- feat: add install script
- feat: setup polkit to let `ubo` user `reboot` and `poweroff`
- refactor: improve `deploy.sh` so that it hasn't a hardcoded username
- feat: assume the package is installed in `/opt/` instead of `/home/pi/`
- refactor: move service related files in `store/` to `store/services/`
- refactor: update to latest versions of `ubo-gui` and `python-redux`

## Version 0.7.14

- refactor: make `create_task` functional for the main application just like its
  services

## Version 0.7.13

- feat: #16 add volume chime
- fix: #16 set the default pulseaudio device to "wm8960-soundcard"

## Version 0.7.12

- fix: #16 use a logarithmic scale for volume

## Version 0.7.11

- feat: #16 connect to the audio controller, play chimes for notifications

## Version 0.7.10

- feat: #15 add `rgb_ring` service and use it for notifications

## Version 0.7.9

- feat: #11 add notification for wifi deletion

## Version 0.7.8

- feat: add notifications service and use it for wireless connection creation

## Version 0.7.7

- refactor: housekeeping - update dependencies, migrate menu data structures to `Immutable`,
  improve typings, organization

## Version 0.7.6

- style: optimize footer space so that it can show 7 icons

## Version 0.7.5

- feat: add `ethernet` service to show ethernet status in a status bar icon
- refactor: move `Fake` class from wifi service to ubo_app for the sake of reusability

## Version 0.7.4

- feat: use redux store for ip service so that other services can use its state
- refactor: use `Sequence` type instead of `list` type whenever it is enough

## Version 0.7.3

- refactor: use `socket` instead of `pythonping` to reduce dependencies and make
  things work without root access
- fix: correct the priority of the icon of the ip service

## Version 0.7.2

- docs: write `README.md` with installation and usage instructions
- refactor: remove the leftovers of the action/event payloads

## Version 0.7.1

- feat: check and update status icons of ip and wifi services
- feat: introduce `UBO_DEBUG` environment variable to control the state of debug
  logs/utilities

## Version 0.7.0

- refactor: remove all `...Payload` classes as `Action`s and `Event`s have no
  other fields other than payload due to `type` being obsolete in this implementation
- refactor: utilize debouncer package in wifi service to listen to and debounce
  dbus events
- refactor: improve responsiveness of wifi connection page

## Version 0.6.2

- fix: avoid dbus connection getting stale
- style: housekeeping - address as many lint errors as possible

## Version 0.6.1

- feat: add `ip` service to show ip addresses of different interfaces of the device

## Version 0.6.0

- refactor: rewrite wifi service using `sdbus_networkmanager`
- refactor: update with the latest features of the latest python-redux version

## Version 0.5.1

- feat: add `install_service` command line argument to setup systemd service
- feat: add `VERBOSE` log level to logging
- feat: add `--run` to deploy script, it doesn't run the app without this option
  anymore

## Version 0.5.0

- refactor: make each service run in its own thread
- fix: weird behavior in RPi's Python, not respecting `submodule_search_locations`

## Version 0.4.4

- chore: directly add headless-kivy-pi as a dependency

## Version 0.4.3

- feat: add wi-fi service and wi-fi flow

## Version 0.4.2

- feat: add camera service
- feat: add camera live viewfinder (bypassing all the Kivy rendering procedures
  for the sake of performance)

## Version 0.4.1

- refactor: use latest version of `python-redux` in which `type` field is
  dropped from actions and events

## Version 0.4.0

- refactor: read `ubo_service_id` and `ubo_service_name` from `__init__.py` file
  of the service
- feat: let services import files from their directory (either by `from .` or
  `from __ubo_service__`)

## Version 0.3.7

- feat: make `dispatch` always run its actions/events in UI thread

## Version 0.3.6

- refactor: improve and simplify `pyproject.toml`

## Version 0.3.5

- refactor: use latest features of ubo-gui to better connect the main menu to store

## Version 0.3.4

- feat: implement the sound store and connect it to the volume widget and mic button

## Version 0.3.3

- chore: add logger

## Version 0.3.2

- refactor: move wifi icon registration to its service

## Version 0.3.1

- chore: add deploy script

## Version 0.3.0

- feat: implement app registration logic and tools
- feat: add wifi app

## Version 0.2.1

- feat: loading services dynamically from 'services' directory and direcotires
  specified in `UBO_SERVICES_PATH`
- feat: implement keyboard and keypad services
- feat: implement main store handling main menu events

## Version 0.1.1

- refactor: make it pip-friendly

## Version 0.1.0

- feat: implement a simple version of redux
