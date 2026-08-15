#!/usr/bin/env sh

# Hardware-in-the-loop audio test runner.
#
# Deliberately DIFFERENT from scripts/test_on_device.sh: that script stops the
# production ubo-app service and runs the core in-process under pytest. The HIL
# tests must run against the *deployed* system — the real assistant subprocess,
# Piper, the real audio device, and a satellite already connected to it over
# WiFi — so ubo-app is left running and the tests talk to it over gRPC.
#
# Usage:
#   uv run poe device:test:hil                 # copy + run
#   index=5 uv run poe device:test:hil         # target ubo-development-pod-5
#
# Requires on the pod: pyserial, and the satellite cabled over USB with
# firmware built WITHOUT the PPP profile (PPP and the log console cannot share
# the USB endpoint — the tests will tell you if this is wrong).

set -o errexit
set -o pipefail
set -o nounset

copy="${copy:-False}"
run="${run:-False}"
results="${results:-False}"
index="${index:-1}"
pytest_args="${pytest_args:-tests/hardware -v -s}"
satellite_port="${satellite_port:-/dev/ttyACM0}"

function run_on_pod_as_root() {
  ssh pi@ubo-development-pod-$index "sudo bash -c '$1'"
}

# pppd owns the satellite's USB console via 99-ubo-esp32-ppp.rules, and the
# harness resets the board — which re-enumerates the USB device and re-triggers
# udev, restarting pppd mid-run and stealing the port. Masking (not just
# stopping) is what prevents the udev-driven restart. Same dance as
# ubo_lvgl/esp32/flash.sh, including restoring on exit.
function hold_off_ppp() {
  run_on_pod_as_root "systemctl mask --runtime ubo-esp32-ppp && systemctl stop ubo-esp32-ppp" || true
}

function restore_ppp() {
  run_on_pod_as_root "systemctl unmask --runtime ubo-esp32-ppp && udevadm trigger --subsystem-match=tty" || true
}

function run_on_pod() {
  if [ $# -lt 1 ]; then
    echo "Usage: run_on_pod <command>"
    return 1
  fi
  ssh pi@ubo-development-pod-$index "sudo -u ubo bash -c 'XDG_RUNTIME_DIR=/run/user/\$(id -u ubo) bash -s'" <<EOF
cd /home/ubo
source /etc/profile
source /home/ubo/.profile 2>/dev/null || true
$*
EOF
}

if [ "$copy" == "True" ]; then
  echo "Generating proto files locally..."
  uv run poe proto:generate:raw proto:compile:raw

  echo "Copying sources to ubo-development-pod-$index..."
  (
    echo ./scripts
    echo ./version.py
    echo ./ubo_app/_version.py
    echo ./ubo_app/rpc/ubo_bindings
    git ls-files --others --exclude-standard --cached
  ) |
    # -r is explicit: --files-from turns OFF recursion even under -a, so the
    # generated (gitignored) ubo_bindings subpackages would arrive as empty
    # directories and `import ubo_bindings.store` would fail on the pod.
    rsync --rsync-path="sudo rsync" --info=progress2 -are ssh --files-from=- \
      --ignore-missing-args ./ \
      pi@ubo-development-pod-$index:/home/ubo/test-runner/ --chown ubo:ubo
fi

if [ "$run" == "True" ]; then
  trap restore_ppp EXIT
  hold_off_ppp
  # NOTE: ubo-app is intentionally NOT stopped — see the header.
  run_on_pod "cd /home/ubo/test-runner && \
    UBO_RUN_HIL=1 \
    UBO_SATELLITE_PORT=$satellite_port \
    uv run --no-sync pytest $pytest_args 2>&1 | tail -120 || true"
fi

if [ "$results" == "True" ]; then
  echo "Fetching recorded sessions..."
  mkdir -p ./tests/hardware/results
  rsync -ae ssh --info=progress2 \
    pi@ubo-development-pod-$index:/home/ubo/.local/share/ubo/assistant_sessions/ \
    ./tests/hardware/results/ || true
fi
