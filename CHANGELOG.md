# Changelog

## Upcoming

- chore: migrate from poetry to uv for the sake of improving performance and dealing with conflicting sub-dependencies
- feat(core): add colors to logs based on their level to make them more readable
- chore: use dynamic version field in `pyproject.toml` based on `hatch.build.hooks.vcs` and publish dev packages on pypi for all pushes to the main branch and all pull requests targeting the main branch
- chore: remove what has remained from poetry in the codebase
- refactor(core): avoid truncating or coloring logs in log files
- feat(web-ui): add web-ui service
- feat(web-ui): process input demands, dispatched on the bus

## Version 1.0.0

- hotfix(users): do not mark the generated password as expired as it will cause boot failures as the os can't autologin into the ubo user when its password is expired
- hotfix(core): render blank screen on the display when `FinishEvent` is dispatched (makes sure display is clean after powering off)

## Version 0.17.1

- feat(display): add `DisplayCompressedRenderEvent` as a compressed version of `DisplayRenderEvent`
- feat(rpc): add reflection to rpc server, limited to root service, but good enough for health checking purposes
- refactor(rpc): preserve the order of fields of `oneof` declarations generated for `Union` types
- refactor(audio): convert `AudioPlayChimeEvent`s to `AudioPlayAudioEvent`s instead of directly playing the chime
- feat(rpc): add `UBO_GRPC_LISTEN_HOST` and `UBO_GRPC_LISTEN_PORT` environment variables
- fix(docker): make sure the `image_menu` view - used nested in an autorun - is re-called when ip addresses are provided

## Version 0.17.0

- feat(rpc): add a proto generator which parses actions and events files and generates proto files for them
- feat(rpc): add `rpc` service with `dispatch` method to let external services dispatch actions and events to the redux bus
- fix(core): check if items added by `RegisterRegularAppAction` or `RegisterSettingsAppAction` cause duplicate keys and raise an informative error if so
- refactor(core): truncate long log items for log level `DEBUG` or lower to avoid cluttering the logs
- refactor(tests): add a delay between initializing different services to make sure they always run in the same order
- feat(rpc): add `subscribe_event` to the rpc service to let external services subscribe to events - closes #1
- test: better tooling for debugging uuid generation in tests
- fix(rpc): deal with messages with no prefix_package meta field
- refactor(core): prepare `REGISTERED_PATHS` earlier for each service, so that import error messages are more meaningful
- fix(vscode): stop and uninstall vscode service when logged out and install and start it when logged in - fixes #114

## Version 0.16.2

- feat(display): add display service and put display content in the bus via `DisplayRenderEvent`
- fix(vscode): restart vscode process whenever a login/logout occurs
- fix(docker): avoid instantiating `RegisterRegularAppAction` in the reducer before service is loaded as it needs service to be registered

## Version 0.16.1

- feat(lightdm): set wayland as the default session for lightdm after installing raspberrypi-ui-mods
- refactor(core): rearange menus
- refactor(docker): move docker settings from docker menu in apps to docker menu in settings, and move all docker apps up to make them direct children of the main apps menu, rename main "Apps" menu to "docker" apps and "Apps" inside settings menu to "Docker"

## Version 0.16.0

- build(packer): remove /etc/xdg/autostart/piwiz.desktop to avoid running piwiz as we already set ubo user
- fix(core): keep a reference for background tasks created with `async_.create_task` to avoid them getting garbage collected and cancelled
- fix(lightdm): update the menu when installation is done
- refactor(lightdm): reorder settings menu and replace "utilities" with "desktop"
- feat(lightdm): show a notification when rpi-connect is started to inform user desktop should be installed for the screen sharing to work
- fix(lightdm): install raspberrypi-ui-mods instead of lightdm to activate wayland and enable rpi-connect screen sharing
- test: fix an issue in tests which caused minor random store state changes, ruining snapshot assertions
- test: add vscode and rpi-connect services to `test_all_services` test
- refactor(housekeeping): improve store imports
- feat(store): add `DispatchItem` and `NotificationDispatchItem` as convenience `ActionItem` subclasses to dispatch actions and events
- feat(users): add `users` service to create, list, delete and change password of system users
- feat(ci): add `ubo-pod-pi5` to the list of github runners for `test`, also use it for `dependencies` and `type-check` jobs
- refactor(core): improve update-manager to be event driven
- feat(core): add `UBO_ENABLED_SERVICES` to complement `UBO_DISABLED_SERVICES` in controlling which services should load
- refactor(vscode): make it regularly read vscode status from its command line interface every second

## Version 0.15.11

- fix(notifications): notifications not getting closed nor updated

## Version 0.15.10

- refactor(core): use `dpkg-query` instead of `apt` python api as loading `Cache` in `apt` is slow and use it in docker service
- refactor(system): add response for docker commands and service commands
- feat(lightdm): add installation options for lightdm package
- refactor(notifications): update the `NotificationWidget` when it is visible and a new notification with the same id is dispatched

## Version 0.15.9

- build(packer): set `autologin-user` to `ubo` in `/etc/lightdm/lightdm.conf`
- feat(core): improve update notification for phase-2 of the update process and add a spinner on top-left
- fix(core): avoid side-effects after `FinishEvent` is dispatched.

## Version 0.15.8

- fix(wifi): improve the logic of wifi onboarding notification
- feat(core): add base image to `/etc/ubo_base_image` and about page

## Version 0.15.7

- refactor(core): general housekeeping, improve resource management in runtime and test environment, minor bug fixes
- build(core): update dependencies to their latest versions

## Version 0.15.6

- fix(audio): add a recovery mechanism for audio service to rebind the sound card if it is not available - closes #83
- fix(voice): remove the gap between sentences
- fix(core): change the power-off menu item icon - closes #151
- refactor(core): migrate `ubo_app/services.py` to `typings/ubo_handle.pyi` as it was only providing types
- fix(core): make sure app exits gracefully before shutdown/reboot and atexit callbacks run - closes #150
- refactor(core): kill the app (so that it restarts) when the reset button is pressed for 0.5 seconds or more and reboot the device when it is pressed for 3 seconds or more - closes #116
- fix(vscode): after login with vscode, the gui now goes back to login code page - closes #143
- fix(core): updating items of the pages after the first page, not being reflected on the screen - closes #149
- feat(rpi-connect): implement `rpi-connect` under `Remote` menu - closes #139
- fix(core): update manager downloads the latest `install.sh` and runs it to do the update - closes #152
- feat(core): add signal management for ubo_app process - closes #156
- fix(core): use fasteners read-write lock implementation for the persistent store - closes #158
- feat(core): improve the user experience of update-manager by making it more verbose about the current state of the update progress - closes #153

## Version 0.15.5

- feat(notifications): add `progress` and `progress_weight` properties to `Notification` object and show the progress on the header of the app
- feat(core): show the progress of the update using the new `progress` property of the `Notification` object
- fix(camera): render the viewfinder on the display even if the display is paused - closes #78
- refactor(core): make the power-off menu, a sub-menu with power-off and reboot action items - closes #123
- fix(core): headed menus not showing the first item in the list - closes #144
- refactor(system): generate the hostname of the device based on a hash of its serial number
- feat(core): show hostname of device on the home page - closes #128
- feat(core): long-pressing the reset button for 3 seconds or more reboots the device - closes #116
- fix(keypad): keypad becoming unresponsive if a key was pressed while the app was loading - closes #118
- fix(camera): closing the camera viewfinder will close the picamera instance so that it can be used again
- refactor(core): use python-fake for faking
- refactor(tests): wait for wifi status icons in `test_wireless`
- refactor(core): move `ubo_app.utils.loop` to `ubo_app.service` and add service properties like `service_id`, `name`, `label`, etc as module level variables to it
- refactor(core): make `UboModuleLoader` to keep a weakref of the module in its cache instead of an actual reference
- refactor(core): use the new `key` property of ubo-gui `Item`s to keep opened menus open when something changes in the parent menus - closes #145, closes #146, closes #147
- fix(core): make sure logs are set up after reading environment variables and before starting the app
- feat(keypad): add epoch time to keypad actions and events in `time` field
- feat(voice): add piper engine to voice service as the default engine and a menu to select the engine - closes #120
- refactor(notification): add `NotificationExtraInformation` with `text`, `piper_text`, and `orca_text` to replace the simple strings passed to `extra_information` field of the `Notification` object
- refactor(audio): rename sound service to audio service
- refactor(audio): drop `pyaudio` and use `simpleaudio` for playback
- feat(core): setting `DEBUG_MODE_MENU` environment variable to truthy values will show a representation of the menu in the logs whenever the current menu is changed
- fix(ip): close sockets opened for testing the internet connection - closes #126

## Version 0.15.4

- fix(core): add `rpi-lgpio` to dependencies to make the LCD work on RPi5
- fix(core): add `dtoverlay=spi0-0cs` to `/boot/firmware/config.txt` to make the LCD work on RPi5
- refactor: general housekeeping, improving typing, linting, resource management, etc
- fix(notifications): avoid auto-closing notifications shown in the notification center
- feat(camera): fail-proof the camera initialization when no camera is connected
- fix(ci): run typecheck on ubo-pod to avoid missing packages
- fix(core): move hostname generation code from `bootstrap()` to `setup()` - closes #141
- build: update bookworm images to the latest version 2024-07-04

## Version 0.15.3

- refactor: update to the latest version of `headless-kivy` and migrate its hardware related code to this codebase
- refactor(sensors): migrate initialization of i2c sensors out of the read function so that it happens once
- fix(system): disable led-ring in RPi5 as it is not supported yet

## Version 0.15.2

- feat: make tests running on an ubo pod visible on its screen

## Version 0.15.1

- refactor: rename "Update Code CLI" to "Redownload Code" - closes #117

## Version 0.15.0

- refactor: wireless flow test is complete, during this process debugging and refactoring is done in different parts of code as the issues were found - closes #52
- feat(core): make file handlers in logging `RotatingFileHandler`s
- feat(tests): add `ChooseMenuItemByIconEvent`, `ChooseMenuItemByIndexEvent`, `ChooseMenuItemByLabelEvent` helper events to be used in tests
- feat(tests): a `setup.sh` in `tests` directory or any of its parent directories is sourced before running tests
- feat(tests): add `wait_for_menu_item` and `wait_for_empty_menu` fixtures

## Version 0.14.3

- feat(tests): add `pyfakefs` to mock filesystem in tests
- feat(tests): add `set_persistent_storage_value` to app fixture
- feat(tests): add `initial_wait`, `attempts` and `wait` parameters to `stability` fixture
- fix(vscode): no longer schedule a status check for vscode every 5 seconds, it now only checks the status when the it runs a command using vscode, one second after running the command and 4 seconds after that
- ci(github): fix release workflow not including assets

## Version 0.14.2

- fix(vscode): show a success notification when the login process is completed instead of when the service runs #96
- refactor(vscode): add name of the vscode instance to the sub heading of the vscode menu when it is running
- fix(vscode): set a timeout for vscode commands - closes #101
- feat(docker): dedicated menu for logging out of registries
- fix(notifications): notifications aren't dismissed when the back button is pressed - closes #104
- fix(voice): update the status message in the voice setup page when the access key is set/cleared - closes #105
- fix(camera): back button in the camera viewfinder doesn't cancel the parent application/menu - closes #106
- fix (vscode): schedule vscode status check using `kivy.clock.Clock` instead of `asyncio` - closes #101

## Version 0.14.1

- fix(docker): handle the case when ip interfaces are not initialized yet
- fix(vscode): show an indicator when it is pending url generation
- fix(core): avoid multiple initial overlaying frames #91
- feat(core): pressing the home button navigates the user to the home page #84
- refactor(wifi): change the onboarding notification messages and make voice service load before wifi service by changing its priority #88
- fix(core): use latest version of headless-kivy-pi to avoid the static noise shown before the first frame is ready to be rendered #86
- build(bootstrap): set `UBO_SERVICES_PATH` to `/home/{{USERNAME}}/ubo_services/` in the service file so that user can easily add their custom services
- fix(voice): remove "clear access key" item when access key is not set #97
- fix(voice): update pvorca to 2.1.0 as they suddenly yanked 1.4.0 in pypi #103
- refactor(vscode): flatten vscode menu items into its main menu #102
- feat(vscode): show a notification with chime and led feedback when VSCode successfully logs in #96
- feat(ip): make the internet icon red when there is no connection #95
- fix(docker): remove ngrok dashboard url from `qrcode_input` prompt message #90
- fix(core): update ubo-gui to the latest version to align menu items with the physical buttons - closes #93
- refactor(docker): update ngrok extra information text messages - closes #100

## Version 0.14.0

- feat(wifi): the wireless onboarding suggestion notification is shown when the device is not connected to any network and it hasn't been shown earlier #71
- feat(notifications): `actions` of `Notification` object are respected and are actually shown in the notification, their type is inheriting the original `ActionItem` and adds `dismiss_notification` boolean to it
- feat(tests): stability fixture saves all the snapshots and writes them to the filesystem if it ever fails
- feat(core): setup error handler for event loops, previously errors happening in event loops were silence
- refactor: all `asyncio.create_subprocess_exec` calls now redirect their `STDOUT` and `STDERR` to `DEVNULL` or `PIPE` to avoid noise in output
- fix(qrcode): qr code sets its state correctly after back button is pressed on it
- fix(docker): qr code output for exposed ports doesn't bundle ip addresses of the device in a single entity, instead a separate qr code is generated for each ip
- refactor: notifications and qr-code prompts now show short messages in their front page and long messages in their extra information section #80
- refactor(wifi): reuse `qrcode_input` instead of the old manual way of taking input from qr code
- feat(qrcode): `qrcode_input` accepts an `extra_information` parameter and passes it to the prompt notification
- feat(notification): add an `on_close` callback to the `Notification` object, called when the notification is closed
- feat: add `OpenApplicationEvent` and `CloseApplicationEvent` events
- feat(voice): automatically remove invalid characters not readable by picovoice from the text to be read so that those characters can still be visible in the text
- build(installation): set `XDG_RUNTIME_DIR` in `bashrc` to make interacting with user `systemd` services easier
- fix(vscode): remove timestamp from state #79

## Version 0.13.5

- feat(vscode): add vscode tunnel support: users can download the cli binary, login, install the service and see the tunnel url as qr code #17

## Version 0.13.4

- build(development): add `Dockerfile`s for development and testing
- docs(development): instructions on setting up development environment and running tests

## Version 0.13.3

- refactor(core): reorganize settings menu #69
- refactor(style): add icons to menu titles
- refactor(core): make pagination more obvious #69
- refactor(core): render the next and previous menu items in place of footer/header when there is such item #76
- fix(notifications): scrollbar doesn't wrap around when scrolling up anymore

## Version 0.13.2

- build(bootstrap): generate a semi-unique id for the device and use it as its hostname, this is to reduce the risk of collision in the network #70
- refactor(ssh): show hostname in the notification of the successful account creation #70
- refactor(ssh): avoid letters I, i, l and O in the generated password #70

## Version 0.13.1

- feat(wifi): use voice action to read the scan hint (instead of mehrdad's voice)
- feat(camera): render a box in viewfinder for the QR code to be scanned #23

## Version 0.13.0

- feat(core): organize settings in four different categories of connectivity, interface, system and apps
- feat(core): parse pronunciation hints in notification's extra info and render them as normal text while passing them to picovoice (used for pronunciation of ssh for example)
- feat (core): add shortcut `s` to write a json dump of the store into `snapshot.json`
- feat(core): add dill package and use it for pickling complex datatypes
- feat(core): add secrets module to abstract storing, recalling and removing secrets
- feat(core): add persistent_store module to abstract storing and recalling store elements
- feat(voice): use the new secrets module to save and load picovoice access key
- feat(docker): use the new secrets module to save and load passwords of different registries
- feat(docker): use the new persistent_store module to save and load docker registry to username mapping
- feat(sound): use the new persistent_store module to save and load playback volume, capture volume, and their mute state

## Version 0.12.7

- feat(notification): make the extra information screen scrollable
- build(bootstrap): add `dtoverlay=gpio-fan,gpiopin=22,temp=60000` to `/boot/firmware/config.txt` to make the fan run if CPU temperature passes 60℃ #64
- fix(audio): run the original `install.sh` script of `wm8960-soundcard` to make the audio work #53
- build(packer): mount the first partition of the image in `/boot/firmware` instead of `/boot` to be compatible with the new linux kernel
- ci(github): download and cache images as it is the slowest part of the build
- feat(sound): `SoundPlayAudioEvent` action for playing an audio sample with type of `Sequence[int]`
- feat(voice): add new service voice with `VoiceReadTextAction`, it uses orca service from picovocie to read text with human voice
- feat(notification): read the extra information of the notification when opened
- feat(ssh): force password change after first login for temporarily created accounts

## Version 0.12.6

- feat(core): notifications now can have an optional `extra_information` field which will cause the notification widget to render an info icon which opens a separate screen to render the extra information
- fix(docker): open_webui now runs in its own network as `hostname` and `network_mode` can't be used together #63
- refactor(keypad): reduce complexities
- feat(keypad): dispatch release actions `KeypadKeyReleaseAction` #39
- fix(keypad): dispatch the state of mic key when keypad service initializes #1

## Version 0.12.5

- fix(notification): avoid passing color components bigger than 255
- feat(ssh): show an error message if anything goes wrong during creating temporary account instead of crashing
- fix(keypad): return from `key_press_cb` if no input is changed
- fix(docker): pulling images is now done with `client.images.pull` #63

## Version 0.12.4

- build(packer): disable userconfig service
- feat(ssh): move username and password to the header of notification so that they render bigger
- fix(system): don't close socket connection after writing the response, client already takes care of closing the connection

## Version 0.12.3

- build: use latest images - 2024-03-15 - of RPi as base images
- feat(core): read serial number from eeprom and add it to sentry reports
- feat(core): add screenshot action (triggered with `p` key)
- fix(keypad): make keypad compatible with kernel 6.6 by using gpiozero
- refactor(core): add `shutdown` method for service threads and worker threads to gracefully cancel async jobs instead of immediately terminating event loops
- refactor(core): remove `_run_in_executer` from async utilities
- refactor: use `logger.exception` in exception handlers
- ci: use latest versions of ruff and pyright

## Version 0.12.2

- feat(lightdm): add lightdm service
- build(packer): disable lightdm service by default
- fix(sound): try restarting `pulseaudio` every 5 seconds when it is not ready (it may be not available in the first boot of desktop image at least)
- refactor(ssh): use our own `monitor_unit` utility function and drop `cysystemd`
- ci: set `SENTRY_RELEASE`
- feat(system): setup sentry for `system_manager`
- refactor(core): `send_command` is now an async function utilizing `asyncio` streams

## Version 0.12.1

- feat(system_manager): commands for starting/stopping/enabling/disabling services
- feat(ssh): menu items for starting/stopping/enabling/disabling ssh service
- feat(ssh): monitor ssh service and update menus accordingly
- refactor: move all system-dependent preparations to `setup.py` to be reused in runtime, tests, etc (currently mostly mocking modules for macOS)
- refactor(bootstrap): move bootstrap from `ubo bootstrap` to its own binary `bootstrap` to keep its runtime isolated and avoid unintended side effects
- fix(ci-cd): expand the size of the filesystem for the default image as it was running out of space during the build process and add `apt-get upgrade`

## Version 0.12.0

- feat(core): add `qrcode_input` utility function to let developers easily take input using qrcode through camera, wireless flow now also uses this function, in dev environment it reads the text from `/tmp/qrcode_input.txt` instead
- feat(docker): add `environment_variables` and `command` to image description, both allowing functions as their values, these functions get evaluated when the image is being created
- refactor(core): improve `load_services` so that `ubo_handle.py` files are enforced to be pure and can't import anything, services can start importing once their thread is started.
- fix(image): add `apt remove orca` to image creation scripts #48
- fix(image): resolve the issue of audio driver installation #53
- refactor(test): stability fixture now stops after 4 seconds
- feat(test): introduce `UBO_DEBUG_TEST_UUID` environment variable for tracking the sequence of uuid generations in the tests, it prints the traceback for each call to `uuid.uuid4` if it is set
- fix(wifi): change `_remote_object_path` to `_dbus.object_path` for sdbus objects #57

## Version 0.11.7

- refactor(style): update `ubo-gui` to the latest version and set placeholder for all menus

## Version 0.11.6

- chore(debug): setup sentry for error tracking

## Version 0.11.4

- feat(docker): add ngrok service (currently serves port 22 with no auth token)
- refactor(style): update `ubo-gui` to the latest version and change all icons to use nerd font icons
- refactor(serviceS): change the loading order of the services
- feat(ssh): add ssh service to create and remove temporary ssh target users
- fix(server): it would miss commands coming together in a single packet, now it waits for the next packet if the current packet is not a complete command and it doesn't miss extra commands in the packet if it has multiple commands.

## Version 0.11.3

- test: add wireless flow test, work in progress
- refactor(services): add `init` parameter to `register_service`
- chore(test): generate and collect screenshots in GitHub workflow
- refactor(test): make the return value of `wait_for` reusable
- refactor(test): organize fixtures in different files
- feat(test): introduce `load_services` and `stability` fixtures

## Version 0.11.2

- chore(test): improve snapshot tests to detect extra/less snapshots too
- chore(test): better organize snapshot results in sub-directories
- chore(test): collect mismatching snapshots (store and window) in GitHub workflow
- chore(test): add `--override-window-snapshots` to `pytest` to intentionally override window snapshots when they have changed
- chore(test): add `--make-screenshots` to `pytest` to create window screenshots to help find the differences visually
- chore(test): monkeypatchings for dynamic parts of the app to make tests consistent
- refactor: general improvements in the codebase to address issues found during writing tests
- chore: add badges to `README.md`
- chore: add `Dockerfile.dev` for development, it helps to build consistent screenshots in macOS

## Version 0.11.1

- chore(test): set up testing framework with initial examples
- chore(test): set up snapshot test helper to compare screenshots of different stages of tests with previous successful tests using hashes

## Version 0.11.0

- feat: add ollama and open-webui docker images
- feat: render a qrcode for each ip x port combination of a container
- feat: add `UBO_DOCKER_PREFIX` to help pull docker images from local registries during development
- feat: let images depend on eachother's ip address to let semi composition
- feat: read the state of all relevant containers during initialization and update the store accordingly
- feat: add `--restart=always` for all containers, in the future we will make it customizable.
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

- chore: create ubo images for main branch based on lite, default and full versions of raspberry os in GitHub workflow
- chore: create GitHub release for main branch in GitHub workflows

## Version 0.10.1

- chore: GitHub workflow to publish pushes on `main` branch to PyPI

## Version 0.10.0

- chore: add integration GitHub workflow to check lint, typing and build issues
- refactor: address all lint issues and typing issues

## Version 0.9.9

- feat: add `monitor_unit` utility function to monitor status changes of systemd units
- refactor: make docker service mostly event-driven

## Version 0.9.8

- hotfix: wait for lingering process to finish and retry usreland `systemctl --user daemon-reload` if needed
- hotfix: the `install_docker.sh` script now runs if an optional flag is set for bootstrap command

## Version 0.9.7

- fix: audio for when pipewire is installed
- fix: set permission for ubo user to disconnect wifi connections
- refactor: setup ubo as a lingering user and migrate ubo-app service from a system wide service to ubo userland service still starting after boot
- feature: ability to customize installation process with environment variables:
  - UPDATE: used for when ubo is installed and it should be updated to the latest version
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

- refactor: upgrade `ubo-led` service `ubo-system` service as a general service to take care of system tasks needing root access
- feat: use `ubo-system` to install and run docker service
- chore: add `--bootstrap` option to `deploy` script, it basically runs `ubo bootstrap`

## Version 0.9.1

- fix: load a module from nested packages into nested packages

## Version 0.9.0

- feat: add docker service to manage docker images/containers
- feat: add `UBO_LOGLEVEL` and `UBO_GUI_LOGLEVEL` environment variables
- feat: add `run_in_executor` to run non-coroutine (non-async) blocking functions without blocking the ui

## Version 0.8.9

- fix: modules loaded in services now get executed only once, avoiding registration of redundant subscriptions and listeners

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
- feat: automatically run update check whenever about menu is opened with a throttling of 10 seconds

## Version 0.8.3

- feat: introduce notification ids as a means to avoid duplicated notifications
- fix: don't show expired notifications
- feat: add a convention for notification ids and status icon ids in `README.me`

## Version 0.8.2

- feat: blank screen when turning off the device, as backlight has a pull up and turns on after devices is turned off

## Version 0.8.1

- feat: power off button now turns off the screen and actually powers off the device

## Version 0.8.0

- feat: update menu showing current version and a button to update ubo-app
- feat: add update system service to automatically install an update in boot time if it is already downloaded
- feat: add install script
- feat: setup polkit to let `ubo` user `reboot` and `poweroff`
- refactor: improve `deploy.sh` so that it hasn't a hardcoded username
- feat: assume the package is installed in `/opt/` instead of `/home/pi/`
- refactor: move service related files in `store/` to `store/services/`
- refactor: update to latest versions of `ubo-gui` and `python-redux`

## Version 0.7.14

- refactor: make `create_task` functional for the main application just like its services

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

- refactor: housekeeping - update dependencies, migrate menu data structures to `Immutable`, improve typings, organization

## Version 0.7.6

- style: optimize footer space so that it can show 7 icons

## Version 0.7.5

- feat: add `ethernet` service to show ethernet status in a status bar icon
- refactor: move `Fake` class from wifi service to ubo_app for the sake of reusability

## Version 0.7.4

- feat: use redux store for ip service so that other services can use its state
- refactor: use `Sequence` type instead of `list` type whenever it is enough

## Version 0.7.3

- refactor: use `socket` instead of `pythonping` to reduce dependencies and make things work without root access
- fix: correct the priority of the icon of the ip service

## Version 0.7.2

- docs: write `README.md` with installation and usage instructions
- refactor: remove the leftovers of the action/event payloads

## Version 0.7.1

- feat: check and update status icons of ip and wifi services
- feat: introduce `UBO_DEBUG` environment variable to control the state of debug logs/utilities

## Version 0.7.0

- refactor: remove all `...Payload` classes as `Action`s and `Event`s have no other fields other than payload due to `type` being obsolete in this implementation
- refactor: utilize debouncer package in wifi service to listen to and debounce dbus events
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
- feat: add `--run` to deploy script, it doesn't run the app without this option anymore

## Version 0.5.0

- refactor: make each service run in its own thread
- fix: weird behavior in RPi's Python, not respecting `submodule_search_locations`

## Version 0.4.4

- chore: directly add headless-kivy-pi as a dependency

## Version 0.4.3

- feat: add wi-fi service and wi-fi flow

## Version 0.4.2

- feat: add camera service
- feat: add camera live viewfinder (bypassing all the Kivy rendering procedures for the sake of performance)

## Version 0.4.1

- refactor: use latest version of `python-redux` in which `type` field is dropped from actions and events

## Version 0.4.0

- refactor: read `ubo_service_id` and `ubo_service_name` from `__init__.py` file of the service
- feat: let services import files from their directory (either by `from .` or `from __ubo_service__`)

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

- feat: loading services dynamically from 'services' directory and direcotires specified in `UBO_SERVICES_PATH`
- feat: implement keyboard and keypad services
- feat: implement main store handling main menu events

## Version 0.1.1

- refactor: make it pip-friendly

## Version 0.1.0

- feat: implement a simple version of redux
