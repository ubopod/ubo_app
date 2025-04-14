# Changelog

## Upcoming

- test: improve test logs in the ci
- refactor(docker): since service setup functions are now run after reducers are initialized, we don't need to pass the signal for loading docker applications through the docker reducer
- refactor(voice): make the menu `Item` parameters like icon and background color, used to show it's selectable and selected/unselected reusable by putting them in `ubo_app/utils/gui.py`
- feat(services): add log level selection sub menu to each service menu and sync it with persistent storage - closes #164
- test(services): set limits for the number of registered listeners and event handlers after all services are loaded in `test_all_services_register`
- refactor(core): wait for all service threads to join before running cleanup functions for dbus connections and the logger
- feat(services): apply log levels set in service settings for each service using `logging.Filter`
- feat(ci): make the build job fail if grpc bindings are not up to date with code
- refactor(core): move pod-id generation logic to `set_pod_id` and "unseed" the seeded random after generating pod id
- refactor(services): make sure services do not do anything, including importing their `setup.py` which can potentially run code in its module scope, by moving `register_reducer(reducer)` write after reducer import, before `init_service` is imported
- chore(scripts): add `--index` for `device:` poe scripts, allowing deployment and tests on multiple devices without the need to constantly change `ubo-development-pod`
- chore: housekeeping, update dependencies, remove unused code, etc
- feat(infrared): add infrared service with settings menu to enable/disable propagating keypad actions as ir commands and receiving ir commands and translating them to keypad actions - closes #160
- refactor(speech-synthesis): rename `voice` service to `speech_synthesis` to make room for a separate `speech_recognition` service

## Version 1.3.0

- fix: remove dependencies of `publish` job of `publish_to_pypi` workflow
- fix: vscode binary now needs to be instructed about the location of the binary with `version use` sub-command - closes #217
- fix: image size being too big for the lite version of the raspberry os
- fix: restart avahi-daemon after the hostname is set in `ubo-system`
- feat: add support for `set`s and `dict`s for rpc api
- feat: `{{hostname}}`, as a template variable, will be replaced with the hostname of the device whenever used in `title` and `content` properties of a `Notification` instance or in the `text`, `picovoice_text` or `piper_text` properties of a `ReadableInformation` instance.
- refactor: minor improvements like add `volume` to `AudioPlayAudioEvent`, metric's `density` of kivy to `DisplayRenderEvent` and `DisplayCompressedRenderEvent`, some housekeeping in syntax, logs and ci/cd scripts
- refactor: to make it easier for other modules to interact with docker containers and compositions, there is now a store action for each interaction and now they run as side effects of those store actions dispatched to the store, instead of directly calling functions
- feat(web-ui): implement react web application for the web-ui service - closes #224
- refactor(web-ui): use mui dialogs for input demands - closes #224
- chore(web-ui): add linting and formatting to the web application code - closes #224
- refactor(web-ui): use webaudio for audio playback in the web application and add an unmute button - closes #224
- feat(web-ui): add side buttons layout, and handle swipe gestures for the web application - closes #224
- feat(web-ui): add dark-mode support for layout buttons and add color scheme switch buttons - closes #224
- fix(web-ui): provide input field for when there is no `fields` nor `pattern` in the `InputDescription`
- refactor(voice): upgrade `access_key` input to use the new `fields` value of the `InputDescription`
- refactor(web-ui): use the same mui interface in static server too (instead of jinja-rendered interface) and add action buttons for all status reported by server - closes #224
- fix(rpi-connect): use `with_state` of the latest python-redux version instead of `view` to avoid memoization of actions - closes #248
- refactor(core,audio,display,keypad,sensors): read and check content of eeprom to determine if a device/service should be initialized or not - closes #223, #closes #249
- fix(core): improve syntax of `str_to_bool`, removing all unnecessary `== 1` postfixes
- feat(core): implement services menu in settings for controlling services - closes #4, closes #226
- feat(core): store services configuration into and read them from the persistent store
- refactor: use the new subscriptions return value of the `setup` function for different services to report subscriptions so that the service manager can clean up the subscriptions when the service is stopped
- fix(core): remove the reference of the async task handle after it is done to avoid memory leaks
- feat(core): clean up status icons of a service when it stops
- refactor(tests): make different parts of code explicitly return their cleanup functions and make test_services wait until all services are completely loaded without any errors plus small improvements to logs
- chore(lint): update ruff to the latest version and update codebase to be compatible with it
- build(installation): remove the line in install.sh uninstalling `RPI.GPIO` as it is no longer needed with the latest release of adafruit-blinka
- build(installation): remove the raspberry pi's ssh daemon banner warning about setting a valid user
- refactor(core): make `subscribe_event` created in services, run the handler in the event loop of the service instead of the event loop of the main thread - closes #226
- refactor: add `ubo_app.colors` and move hardcoded color codes to it
- feat: add menu switch for service threads to enable/disable auto-run and auto-rerun of services - closes #227
- build(install): avoid swallowing stdout of the `pip install` command in the `install.sh`, lock onnxruntime to 1.20.1, related: <https://github.com/microsoft/onnxruntime/issues/23957>
- test: improve cleanup and add explicit wait for loaded services to unload at the end of `test_services` test
- feat(core): add a barrier for services after they register their reducer, they will pass it only when the rest of them have registered their reducer - closes #163
- refactor(core): replace `kivy.clock.Clock.create_trigger` as the scheduler of the store with a new in house implementation of a scheduler using `asyncio` running in a separate thread and multiple improvements in resource cleanup, test utilities to ensure tests are reproducible and don't fail randomly
- docs: add a section for adding new services, mentioning general patterns, to avoid common mistakes
- refactor(core): better handle circular references in formatting log messages
- fix(core): wrap `callback` call of the scheduler in `try` to avoid the scheduler stopping when an exception is raised in its thread
- refactor(docker): make docker container menus load even if `ip` service is not available
- test: mock `has_gateway` and better mock `send_command` to make it return `done` instead of `Connected` when the command is not `connection`
- refactor(core): use latest version of `python-redux` and `ubo-gui` and remove all `@mainthread` decorators for actions on the menu as `ubo-gui` now takes care of running them in the main thread itself
- fix(core): improve resource cleanup of service threads so that they can be restarted after being stopped
- refactor(core): defer attaching the main reducer to the root reducer using `CombineReducerRegisterAction` to avoid circular imports or sacrificing the purity of reducers.
- fix(core): add cleanup for gpio pins including display pins and run `gpiozero.devices._shutdown` as part of the cleanup process
- test: wait for scheduler to completely stop before stopping the kivy app to make sure no `kivy.clock.Clock` event gets scheduled after the app is stopped
- fix(core): add display cleanup for raspberry pi 4 as adafruit uses `RPi.GPIO` in pi 4 instead of `lgpio` which it uses for pi 5 and we already have a cleanup for it
- test: add `UBO_TEST_INVESTIGATION_MODE` to enable advanced and costly tools like recording stack-trace of `cell`s, generating dependency graph using `objgraph` and running pdb session when memory leak is found to better investigate memory leaks
- test: move all dbus custom interfaces in `ubo_app.utils.dbus_interfaces` and preserve it in test cleanup, this is due to sdbus having a hidden mapping of dbus interfaces to their implementations in the C code and it doesn't clean up the mapping when the interface is removed
- refactor: avoid using `Clock.schedule_interval` and replace it with `asyncio.sleep` in services needing to periodically run a function
- test: add `test_menu`, as the first in a category of tests purposed to reproduce rare and hard-to-reproduce bugs: these tests run a few times normally, but when `UBO_TEST_INVESTIGATION_MODE` environment variable is set, they repeat the expected reproduction steps thousands of times until the bug is reproduced, and then run a pdb session for investigation
- refactor(services): better error representation containing more content in a single page
- fix(sensors): explicitly set the `light_integration_time` for the light sensor - closes #269
- fix(core): add `task_runner` parameter to `async_.create_task` and use it with `async_.get_task_runner` in store event handlers instead of directly calling the task runner to make sure a reference to tasks are stored in the memory until they are finished, handle by `async_.create_task` - closes #247, closes #266
- chore: update pyright and fix/silent newly reported type errors
- fix(core): improve `has_gateway` utility function to ignore default routes with local scope - closes #251
- fix(display): decrease baudrate from 70,000,000 to 60,000,000 to avoid residual noise on the display - closes #236
- fix(web-ui): don't interpret keys pressed outside the `#web-app-root`, or keys pressed on `HTMLInputElement`, `HTMLTextAreaElement`, `HTMLSelectElement` and `HTMLButtonElement` as interactions with the pod
- fix(system): make system process completely exit when it's done so that systemd can restart it, the exit used to get blocked by the `check_connection` thread, also make it not exit simply because a client sends an empty datagram, the client may have crashed but system process doesn't need to exit - closes #272
- refactor(ip): remove python-ping package and the connection monitoring code in the system-manager, use system ping command instead, this is because none of the python packages providing ping functionality are actively maintained and ping command has the benefit of not needing to run as root, lowering the communication traffic between the system process and the main process - closes #267
- refactor(core): move setting gpio 17 to `config.txt` so that it happens on boot and remove it from `hardware_initialization`
- refactor(core): make the scheduler compensate for the time it took to run the last scheduled event, by waiting less time in the next scheduled event, also sync its frequency with the frequency of the display updates
- feat(core): handle system signal `USR1` as the signal to initiate `ipdb` only if `DEBUG_MODE_PDB_SIGNAL` is set
- refactor(system): improve the user experience of the reset button, add a pattern for restarting the app without killing it
- refactor(core): add unified API to access “current service” via thread-local, parent thread, or call stack
- refactor(core): better representation of errors in logs and service menus
- fix(ip): make sure the connection status is set to not-connected when ping is not generating any output
- refactor(services): avoid silencing caught exceptions in services by either reraising them so that they are caught and reported by the global exception handler or directly reporting them
- fix(audio): make audio run the `unbind` and `bind` sequence if the audio card is not listed by `alsaaudio.cards`
- fix(audio): replace wareshare repo with ubopod fork
- refactor(wifi): show wifi onboarding only on ubo-pod, and initiate the wifi input over hotspot on non-ubo-pods
- fix(audio): make sure `set_playback_mute`, `set_playback_volume` and `set_capture_volume` are applied on the audio card, even if audio manager is not initialized when these methods are called

## Version 1.2.2

- fix: temperature sensor is on 0x48, not 0x44

## Version 1.2.1

- fix: tenacity is now a production dependency
- chore: add pypi publish and automatic release github workflows

## Version 1.2.0

- chore: add `log_async_process` to log the output of an async processes in a notification if they don't run successfully
- refactor(core): housekeeping: rename `extra_information` to `qr_code_generation_instructions` in `ubo_input`, add `.tmpl` extension for extension files, use `textarea` for `LONG` input field type in web dashboard, rename `..._HOST` env variables to `..._ADDRESS`, use underscore thousand separators for big numbers in codebase
- feat(docker): support docker compositions and add a way to import `docker-compose.yml` files
- feat(docker): add instructions and icon for docker compositions
- refactor(core): rerender screen when rendering on the display is resumed like when returning from viewfinder to avoid artifacts
- refactor(docker): make composition menus responsive: showing spinner, etc
- fix: pass raw bytes to `DisplayRenderEvent` and `DisplayCompressedRenderEvent` to avoid encoding issues
- fix: add ".local" to hostname in users menus - closes #134
- fix: use stdout instead of stderr for reading rpi-connect process output - closes #174
- feat: hold update until the app creates a file signaling it is loaded - closes #177
- feat: setup a wifi hotspot for when the a web-ui input is demanded and the device is not connected to any network - closes #169
- feat: let the user upload directory content of the docker composition they are creating - closes #202
- feat: use `pod_id` as the ssid of the wifi hotspot
- feat: add dark mode for web-ui
- docs: update development documentation
- feat(web-ui): automatically run the wifi creation procedure when there is no ssid saved in the network manager and no default gateway is set - closes #214
- feat(web-ui): use captive portal in the hotspot started by web-ui - closes #211
- fix(core): an issue where a tuple of lists where passed as active_inputs instead of a list due to an unwanted comma - closes #212
- fix(core): high cpu usage due to the while loop going non-blocking when the ping raised an exception - closes #216
- feat(core): add a utility function to apply templates to filesystem based on a templates directory, while taking backups of the original files and another utility function to restore the backups
- fix(web-ui): run `iw wlan0 set power_save off` before running hotspot to avoid the soft block - closes #222
- refactor(ci): use new github runner arm images for building images
- feat(web-ui): add `ubo-redirect-server` service
- refactor(web-ui): add notifications for when starting/stopping the hotspot fails in the system manager
- refactor(web-ui): move starting/stopping of the required hotspot system services to the `ubo-hotspot` service (the more general version of the `ubo-redirect-server` service which runs the redirect server as its main process.)
- fix(core): uninstall RPi.GPIO after installing python packages in `install.sh` [related](https://github.com/adafruit/Adafruit_Blinka/issues/910) - closes #231
- fix(web-ui): avoid web-ui stop procedure being triggered when qr-code input is cancelled
- fix(system): run `time.sleep` for both branches of the ping loop (success and failure) to avoid high cpu usage of the system process
- fix(camera): avoid values read from qrcode being overridden by `None` values of alternative patterns - closes #230
- fix(wifi): wait a few seconds before creating the wifi connection if the provided input result has the input method `WEB_DASHBOARD` - closes #230
- fix(wifi): set `network_manager.wireless_enabled` for when hotspot is being turned off and also before creating a wifi connection and before connecting to a wifi network - closes #230
- fix(keypad,sensors): retry i2c initializations - closes #234
- fix(wifi): make `get_saved_wifi_ssids` return empty list in non-rpi environments

## Version 1.1.0

- chore: migrate from poetry to uv for the sake of improving performance and dealing with conflicting sub-dependencies
- feat(core): add colors to logs based on their level to make them more readable
- chore: use dynamic version field in `pyproject.toml` based on `hatch.build.hooks.vcs` and publish dev packages on pypi for all pushes to the main branch and all pull requests targeting the main branch
- chore: remove what has remained from poetry in the codebase
- refactor(core): avoid truncating or coloring logs in log files
- feat(web-ui): add web-ui service
- feat(web-ui): process input demands, dispatched on the bus
- feat(keypad): ability to use key-combinations, set key combinations for screenshot, snapshot and quit
- feat(web-ui): add `fields` in `InputDescription` with `InputFieldDescription` data structures to describe the fields of an input demand in detail
- fix(users): avoid setting user as sudoer when it performs a password reset
- feat(ip): use pythonping to perform a real ping test instead to determine the internet connection status instead of opening a socket
- feat(core): user can start/end recording actioning by hitting r, actions will be recorded in `recordings/` directory and the last recording can be replayed by hitting `ctrl+r` - closes #187
- feat(core): use new `SpinnerWidget` of ubo-gui to show unknown progress in notifications, and add `General` sub menu to `System` settings menu to host ubo-pod/ubo-app related settings, currently it has `Debug` toggle to control a debug feature of `HeadlessWidget` - closes #190
- feat(core): add recording and replaying indicators, avoid replaying while recording and vice versa, move keypad events to its own reducer as it has grown too big

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
- refactor(services): change the loading order of the services
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
